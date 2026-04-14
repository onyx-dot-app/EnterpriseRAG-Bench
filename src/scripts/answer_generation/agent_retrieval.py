"""CLI agent script for answering questions by searching the document corpus.

Each question is answered by an agentic loop that uses a shell run() tool, a
select_doc_by_dsid() tool for tracking relevant documents, and a finish(answer)
tool.  The agent's working directory is set to the
sources directory so all commands operate relative to the corpus root.  Results
are written to a JSONL file compatible with the evaluation harness.

Two-layer architecture
======================

The command execution pipeline is split into two layers with distinct
responsibilities.  The separation is necessary because raw pipe data must
flow between commands unmodified, while the LLM has context-window and
text-only constraints that require post-processing.

**Layer 1 — Execution layer** (``parse_chain`` / ``execute_chain``):
    Runs the actual shell commands.  Pipe segments pass raw bytes between
    each other with no truncation, no metadata injection, and no formatting.
    This keeps pipe semantics correct — truncating ``cat`` output before it
    reaches ``grep`` would produce incomplete search results, and injecting
    ``[exit:0]`` into pipe data would become a spurious search hit.

    The only checks that happen inside the chain are:
    - Command allowlist validation (first token of the first segment).
    - Binary detection on the *final* segment's stdout.
    - Early exit when any segment produces stderr with a non-zero exit code.

**Layer 2 — Presentation layer** (``_format_tool_output`` + assembly in ``_run``):
    Runs *after* the chain completes and the final output is ready to return
    to the LLM.  Handles everything the LLM needs but the execution layer
    must not touch:
    - Truncation: output exceeding ``TRUNCATION_MAX_LINES`` or
      ``TRUNCATION_MAX_CHARS`` is cut, with the full output saved to a temp
      file the agent can navigate with grep/tail.
    - Context-aware hints: null-field guidance, zero-result counters,
      repeat-command detection, subdirectory navigation hints.
    - Metadata footer: exit code, elapsed time, command index, session time.

Usage:
    python -m src.scripts.answer_generation.agent_retrieval [OPTIONS]

Args:
    --parallelism      Number of parallel workers (default: 1)
    --limit            Maximum number of questions to process
    --subset-per-type  Only process first N questions of each question_type
    --questions-file   Path to questions JSONL (default: questions.jsonl)
    --output           Output JSONL path (default: answer_evaluation/answers_agent.jsonl)
    --question-id      Process only this specific question ID
    --resume           Skip questions already present in the output file
    --model            Override the LLM model name for all calls (default: LLM_MODEL_NAME env var)
    --reasoning-level  Reasoning effort: low, medium, high (default: medium)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from src.llm.auto_conversation import prune_messages, run_agent_conversation
from src.llm.factory import get_cheap_llm, get_llm
from src.llm.interface import LLMInterface, Message, ReasoningLevel
from src.paths import QUESTIONS_PATH, SOURCES_DIR, UUID_INDEX_PATH
from src.utils.cli import confirm_yes_no
from src.utils.document_index import load_or_build_uuid_index, rebuild_uuid_index
from src.utils.questions import append_to_jsonl
from src.prompts.agent_retrieval_answer_gen import (
    AGENT_RETRIEVAL_SYSTEM_PROMPT,
    ALLOWED_COMMANDS,
    COMPACTION_CONTINUATION_MESSAGE,
    COMPACTION_SYSTEM_PROMPT,
    COMPACTION_USER_PROMPT,
    OUT_OF_TIME_USER_MESSAGE,
    RUN_TOOL_NAME,
    SELECT_DOC_TOOL_NAME,
    SELECT_DOC_TOOL_SCHEMA,
    COMMAND_TIMEOUT_SECONDS,
    SELECTED_DOC_FAILURE_RESPONSE,
    SELECTED_DOC_REMOVAL_RESPONSE,
    SELECTED_DOC_SUCCESS_RESPONSE,
    build_run_tool_schema,
    build_search_strategy_tips,
)
from src.tools import READ_TOOL
from src.tools.tool_implementations.document_read import DocumentReadTool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_TIMEOUT_SECONDS = 600  # 10 minutes per question

# Maximum concurrent subprocess executions across all agent threads.
# Sized to CPU count so shell commands (rg, grep, find) don't fight for cores
# while allowing many more agents to wait on LLM responses concurrently.
_SUBPROCESS_SLOTS = int(os.environ.get("AGENT_SUBPROCESS_SLOTS", os.cpu_count() or 8))
_subprocess_semaphore = threading.Semaphore(_SUBPROCESS_SLOTS)

# Layer 2 truncation limits — output is truncated at whichever is hit first.
# Aligned with opencode defaults (2 000 lines / 50 KB).
TRUNCATION_MAX_LINES = 2_000
TRUNCATION_MAX_CHARS = 50_000

# Search/glob-specific result cap (matches opencode's per-tool limits).
# Applied when grep/rg/find/glob is the *last* command in a pipe chain.
SEARCH_RESULT_MAX_LINES = 100
_SEARCH_RESULT_COMMANDS: set[str] = {"grep", "rg", "find", "glob"}

# Budget for the text blob sent to the compaction LLM.
_COMPACTION_INPUT_MAX_CHARS = 150_000
# Individual tool-result outputs are truncated to this many chars in the
# compaction input so the summary LLM sees a balanced view of all steps.
_COMPACTION_TOOL_RESULT_CHARS = 1_000

# Effective command set — starts as the full allowlist and is narrowed by
# check_available_commands() at startup so that LLM-facing prompts, tool
# schemas, and validation errors only reference commands actually on PATH.
_active_commands: set[str] = set(ALLOWED_COMMANDS)


def check_available_commands() -> list[str]:
    """Check which ALLOWED_COMMANDS are missing from the system PATH.

    Also narrows ``_active_commands`` to only those that are available so
    that system prompts, tool descriptions, and validation errors shown to
    the LLM only reference usable commands.

    Returns a list of command names that could not be found.
    """
    global _active_commands
    missing = [cmd for cmd in sorted(ALLOWED_COMMANDS) if shutil.which(cmd) is None]
    _active_commands = ALLOWED_COMMANDS - set(missing)
    return missing


# ---------------------------------------------------------------------------
# Layer 2: Presentation layer helpers
# ---------------------------------------------------------------------------


def _extract_search_base_path(command: str) -> str | None:
    """Extract the normalised base directory from an rg/grep command.

    With cwd set to the sources directory, commands use relative paths like
    ``rg "keyword" jira/`` or ``rg "keyword" .``.
    """
    if not re.search(r"\b(rg|grep)\b", command):
        return None
    m = re.search(r"(?:^|\s)\.?/?([\w\-]+)/", command)
    if m:
        return m.group(1)
    if re.search(r"\s\./?(?:\s|$)", command):
        return "."
    return None


def _build_subdirs_hint(sources_dir: str) -> str:
    """One-line listing of source subdirectories for zero-result navigation."""
    if not os.path.isdir(sources_dir):
        return ""
    subdirs = sorted(
        d
        for d in os.listdir(sources_dir)
        if os.path.isdir(os.path.join(sources_dir, d))
    )
    if not subdirs:
        return ""
    return "Available subdirectories: " + "  ".join(f"{d}/" for d in subdirs)


def _update_and_get_zero_hint(
    counts: dict[str, int],
    command: str,
    output: str,
    rc: int,
    subdirs_hint: str,
    threshold: int = 5,
) -> str:
    """Update zero-result consecutive counts; return hint string when threshold hit."""
    base = _extract_search_base_path(command)
    if base is None:
        return ""
    if output.strip() == "" and rc == 1:
        counts[base] = counts.get(base, 0) + 1
        if counts[base] == threshold:
            note = f"[note: {threshold} consecutive zero-result searches in {base}]"
            return f"{note}\n{subdirs_hint}" if subdirs_hint else note
    else:
        counts[base] = 0
    return ""


def _format_tool_output(output: str, command: str = "") -> tuple[str, str]:
    """Format raw command output for LLM consumption (Layer 2).

    Applies truncation (``TRUNCATION_MAX_LINES`` or ``TRUNCATION_MAX_CHARS``,
    whichever is hit first) and saves full output to a navigable temp file
    when truncated.

    Returns:
        (formatted_output, truncation_line) where truncation_line is empty
        if no truncation occurred, or a ``--- output truncated ... ---``
        string to insert before the footer.
    """
    lines = output.splitlines(keepends=True)
    total_lines = len(lines)
    total_chars = len(output)

    # Check if truncation is needed
    truncated_by_lines = total_lines > TRUNCATION_MAX_LINES
    truncated_by_chars = total_chars > TRUNCATION_MAX_CHARS

    if not truncated_by_lines and not truncated_by_chars:
        return output, ""

    # Truncate by whichever limit is hit first
    if truncated_by_lines:
        shown = "".join(lines[:TRUNCATION_MAX_LINES])
        # Also enforce char limit on the line-truncated result
        if len(shown) > TRUNCATION_MAX_CHARS:
            shown = shown[:TRUNCATION_MAX_CHARS]
        trunc_desc = f"{total_lines} lines, {total_chars} chars"
    else:
        shown = output[:TRUNCATION_MAX_CHARS]
        trunc_desc = f"{total_chars} chars"

    truncation_line = f"--- output truncated ({trunc_desc}) ---"

    return shown, truncation_line


def _apply_search_truncation(output: str, command: str) -> tuple[str, str]:
    """Cap grep/glob output at ``SEARCH_RESULT_MAX_LINES``.

    When the *last* command in the chain is a search or glob command and its
    output exceeds the limit, the full output is saved to a temp file and
    the visible output is truncated with a navigation hint.

    Returns ``(possibly_truncated_output, hint)`` where *hint* is empty
    when no truncation occurred.
    """
    segments = parse_chain(command)
    if not segments:
        return output, ""

    last_cmd = segments[-1].command.strip()
    try:
        tokens = shlex.split(last_cmd)
    except ValueError:
        return output, ""
    if not tokens or os.path.basename(tokens[0]) not in _SEARCH_RESULT_COMMANDS:
        return output, ""

    lines = output.splitlines(keepends=True)
    if len(lines) <= SEARCH_RESULT_MAX_LINES:
        return output, ""

    truncated = "".join(lines[:SEARCH_RESULT_MAX_LINES])
    total = len(lines)
    dropped = total - SEARCH_RESULT_MAX_LINES
    hint = f"({dropped} more results truncated)"
    return truncated, hint


# ---------------------------------------------------------------------------
# Context compaction
# ---------------------------------------------------------------------------


def _messages_to_text(
    messages: list[Message],
    tool_result_limit: int = _COMPACTION_TOOL_RESULT_CHARS,
) -> str:
    """Serialise a message list into readable text for the compaction LLM.

    Tool-result outputs are individually capped at *tool_result_limit* chars
    so that the summary input stays within budget even after many tool calls.
    """
    parts: list[str] = []
    for i, msg in enumerate(messages):
        if msg.role == "system":
            continue
        elif msg.role == "user":
            label = "[Original Question]" if i == 1 else "[User]"
            parts.append(f"{label}\n{msg.content}")
        elif msg.role == "assistant":
            if msg.content:
                parts.append(f"[Assistant]\n{msg.content}")
        elif msg.role == "tool_call" and msg.tool_call:
            args_str = json.dumps(msg.tool_call.args)
            parts.append(f"[Tool: {msg.tool_call.name}] {args_str}")
        elif msg.role == "tool_result":
            content = msg.content or ""
            if len(content) > tool_result_limit:
                content = content[:tool_result_limit] + "\n... [truncated]"
            parts.append(f"[Result]\n{content}")
    return "\n\n".join(parts)


def make_context_compaction_fn(
    quiet: bool = False, cheap_model: str | None = None
) -> Any:
    """Create a context compaction callback for ``run_agent_conversation``.

    This callback is invoked **reactively** — only when the LLM rejects a
    request because the context window is full.  It serialises the
    conversation, sends it to a cheap LLM for summarisation, and replaces
    the messages with ``[system, question, summary, continuation]``.
    Falls back to the simple ``prune_messages`` if the LLM call fails.
    """

    def _compact(messages: list[Message]) -> None:
        total_chars = sum(len(m.content or "") for m in messages)

        # --- build compaction input ------------------------------------
        conversation_text = _messages_to_text(messages)
        if len(conversation_text) > _COMPACTION_INPUT_MAX_CHARS:
            # Keep the tail (most recent research) when the text is too long.
            conversation_text = (
                "... [earlier conversation truncated] ...\n\n"
                + conversation_text[-_COMPACTION_INPUT_MAX_CHARS:]
            )

        summary_messages: list[Message] = [
            Message(
                role="system",
                content=COMPACTION_SYSTEM_PROMPT,
            ),
            Message(
                role="user",
                content=conversation_text + "\n\n" + COMPACTION_USER_PROMPT,
            ),
        ]

        # --- call cheap LLM for summary --------------------------------
        try:
            compact_llm = get_cheap_llm(
                tools=None, quiet=True, reasoning_level=None, model=cheap_model
            )
            summary = ""
            for chunk in compact_llm.generate(summary_messages):
                if isinstance(chunk, str):
                    summary += chunk
        except Exception as exc:
            if not quiet:
                print(
                    f"[compaction] LLM summary failed ({exc}), "
                    "falling back to pruning"
                )
            prune_messages(messages)
            return

        if not summary.strip():
            prune_messages(messages)
            return

        # --- replace messages with compacted version -------------------
        system_msg = messages[0]
        user_msg = messages[1]

        messages.clear()
        messages.extend(
            [
                system_msg,
                user_msg,
                Message(role="assistant", content=summary),
                Message(role="user", content=COMPACTION_CONTINUATION_MESSAGE),
            ]
        )

        new_chars = sum(len(m.content or "") for m in messages)
        if not quiet:
            print(f"[compaction] reduced from {total_chars:,} to {new_chars:,} chars")

    return _compact


# ---------------------------------------------------------------------------
# System prompt & tool schemas (built dynamically from _active_commands)
# ---------------------------------------------------------------------------


def build_tools(read_tool: DocumentReadTool) -> list[dict[str, Any]]:
    """Build the tool schema list with the current active command set."""
    return [
        build_run_tool_schema(_active_commands),
        read_tool.get_schema(include_display_name=False),
        SELECT_DOC_TOOL_SCHEMA,
    ]


def build_system_prompt(corpus_size: int) -> str:
    """Build the system prompt by formatting the template with active commands."""
    allowed_list = ", ".join(sorted(_active_commands))
    tips = build_search_strategy_tips(_active_commands)
    return AGENT_RETRIEVAL_SYSTEM_PROMPT.format(
        allowed_commands=allowed_list,
        corpus_size=corpus_size,
        **tips,
    )


# ---------------------------------------------------------------------------
# Chain parser
# ---------------------------------------------------------------------------


class ChainSegment:
    """A single command segment plus the operator that follows it."""

    def __init__(self, command: str, operator: str | None = None) -> None:
        self.command = command.strip()
        self.operator = operator  # None, '|', '&&', '||', ';'


def parse_chain(command_string: str) -> list[ChainSegment]:
    """Parse a shell command string into segments respecting quoted strings."""
    segments: list[ChainSegment] = []
    current: list[str] = []
    i = 0
    n = len(command_string)

    while i < n:
        ch = command_string[i]

        if ch in ('"', "'"):
            quote_char = ch
            current.append(ch)
            i += 1
            while i < n and command_string[i] != quote_char:
                if command_string[i] == "\\" and i + 1 < n:
                    current.append(command_string[i])
                    current.append(command_string[i + 1])
                    i += 2
                else:
                    current.append(command_string[i])
                    i += 1
            if i < n:
                current.append(command_string[i])
                i += 1
            continue

        if i + 1 < n:
            two = command_string[i : i + 2]
            if two in ("&&", "||"):
                segments.append(ChainSegment("".join(current), two))
                current = []
                i += 2
                continue

        if ch == "|":
            segments.append(ChainSegment("".join(current), "|"))
            current = []
            i += 1
            continue

        if ch == ";":
            segments.append(ChainSegment("".join(current), ";"))
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    remaining = "".join(current).strip()
    if remaining:
        segments.append(ChainSegment(remaining, None))

    return [s for s in segments if s.command]


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data


def _validate_first_command(command: str) -> str | None:
    """Return an error message if the first token is not in the allowed list."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    cmd_name = os.path.basename(tokens[0])
    if cmd_name not in _active_commands:
        allowed = ", ".join(sorted(_active_commands))
        return (
            f"[error] command '{cmd_name}' is not allowed. "
            f"Allowed commands: {allowed}. "
            "Use rg for search, jq for JSON extraction, ls/find to explore."
        )
    return None


def execute_chain(
    command_string: str, cwd: str | None = None
) -> tuple[str, int, float]:
    """Execute a (potentially piped) command chain.

    Returns:
        (output, exit_code, elapsed_ms)
    """
    t0 = time.monotonic()
    segments = parse_chain(command_string)

    if not segments:
        elapsed = (time.monotonic() - t0) * 1000
        available = ", ".join(sorted(_active_commands))
        return (
            f"[error] empty command — available: {available}",
            1,
            elapsed,
        )

    error = _validate_first_command(segments[0].command)
    if error:
        elapsed = (time.monotonic() - t0) * 1000
        return (error, 1, elapsed)

    stdin_data: bytes | None = None
    last_stdout: bytes = b""
    last_returncode: int = 0

    i = 0
    while i < len(segments):
        seg = segments[i]
        try:
            proc = subprocess.run(
                seg.command,
                shell=True,
                input=stdin_data,
                capture_output=True,
                cwd=cwd,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - t0) * 1000
            return (
                f"[error] command timed out after {COMMAND_TIMEOUT_SECONDS} seconds. "
                "Try narrowing the search: use `find -name` for filename discovery "
                "or scope content search to a specific subdirectory.",
                1,
                elapsed,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return (
                f"[error] command failed: {exc} — check syntax and try again.",
                1,
                elapsed,
            )

        stdout = proc.stdout
        stderr = proc.stderr
        rc = proc.returncode

        # Only check for binary on the final output — intermediate pipe
        # segments may legitimately contain null bytes (e.g. find -print0).
        is_last = seg.operator is None
        if is_last and _is_binary(stdout):
            elapsed = (time.monotonic() - t0) * 1000
            return (
                "[error] binary file detected.",
                1,
                elapsed,
            )

        # Early exit on real errors (non-zero rc with stderr) for any operator.
        # A non-zero rc *without* stderr is normal (e.g. grep no-match → rc=1)
        # and should continue through the chain.
        if rc != 0 and stderr:
            elapsed = (time.monotonic() - t0) * 1000
            error_output = stderr.decode("utf-8", errors="replace").strip()
            return (f"[stderr] {error_output}", rc, elapsed)

        operator = seg.operator

        if operator == "|":
            stdin_data = stdout
        elif operator == "&&":
            if rc != 0:
                # && semantics: stop chain on any failure
                last_stdout = stdout
                last_returncode = rc
                break
            stdin_data = None
        elif operator == ";":
            stdin_data = None
        elif operator == "||":
            if rc == 0:
                break
            stdin_data = None
        else:
            # Last segment (operator is None)
            last_stdout = stdout
            last_returncode = rc
            break

        last_stdout = stdout
        last_returncode = rc
        i += 1

    elapsed = (time.monotonic() - t0) * 1000
    decoded = last_stdout.decode("utf-8", errors="replace")
    return (decoded, last_returncode, elapsed)


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------


def make_run_tool_executor(
    cwd: str | None = None,
    session_start: float | None = None,
) -> tuple[Any, Any]:
    """Create a run tool executor with per-session state.

    Tracks per-session state for Layer 2 presentation signals:
    - cmd index + session elapsed  → metadata footer
    - exact command history        → repeat-command annotation
    - zero-result counts per path  → subdirectory navigation hint after 5 misses

    Returns:
        (executor, get_semaphore_wait) where *get_semaphore_wait* is a
        callable returning the cumulative seconds this executor spent
        waiting for a subprocess semaphore slot.  The caller can feed
        this into ``run_agent_conversation`` via ``deadline_credit_fn``
        so that contention time is not charged against the question
        timeout.
    """
    _t0 = session_start if session_start is not None else time.monotonic()
    _cmd_index = [0]
    _seen: dict[str, int] = {}  # command → first cmd index
    _zero_counts: dict[str, int] = {}  # normalised base path → consecutive zeros
    _subdirs_hint = _build_subdirs_hint(os.path.abspath(SOURCES_DIR))
    _semaphore_wait_total = [0.0]
    _wait_lock = threading.Lock()

    def _run(command: str) -> str:
        _cmd_index[0] += 1
        idx = _cmd_index[0]
        session_elapsed = time.monotonic() - _t0

        # Acquire a subprocess slot; track wait time so it can be credited
        # back to the question timeout budget.
        wait_start = time.monotonic()
        _subprocess_semaphore.acquire()
        wait_elapsed = time.monotonic() - wait_start
        if wait_elapsed > 0.01:  # only track meaningful waits
            with _wait_lock:
                _semaphore_wait_total[0] += wait_elapsed
        try:
            # --- Layer 1: execute the command chain (raw, unmodified output) ---
            output, rc, elapsed_ms = execute_chain(command, cwd=cwd)
        finally:
            _subprocess_semaphore.release()

        # --- Layer 2: format output for LLM consumption ---

        # Repeat detection
        repeat_prefix = ""
        if command in _seen:
            repeat_prefix = (
                f"[note: identical to cmd #{_seen[command]} — result unchanged]\n"
            )
        else:
            _seen[command] = idx

        # Zero-result counter
        zero_hint = _update_and_get_zero_hint(
            _zero_counts, command, output, rc, _subdirs_hint
        )

        # Search/glob result cap (100 lines) — runs before the generic
        # truncation so the full output is saved to a navigable temp file.
        output, search_hint = _apply_search_truncation(output, command)

        # Generic truncation, null hints, overflow file
        output, truncation_line = _format_tool_output(output, command=command)

        # Metadata footer
        footer = f"[exit:{rc} | {elapsed_ms:.0f}ms | cmd #{idx} | session: {session_elapsed:.0f}s]"

        # Assemble final result: output → hints → truncation → footer
        parts: list[str] = []
        if repeat_prefix:
            parts.append(repeat_prefix)
        parts.append(output)
        if search_hint:
            parts.append(search_hint)
        if zero_hint:
            parts.append(zero_hint)
        if truncation_line:
            parts.append(truncation_line)
        parts.append(footer)
        return "\n".join(parts)

    def _get_semaphore_wait() -> float:
        with _wait_lock:
            return _semaphore_wait_total[0]

    return _run, _get_semaphore_wait


def make_select_doc_executor(
    uuid_index: dict[str, str],
    selected_ids: set[str],
) -> Any:
    """Create an executor for the select_doc_by_dsid tool.

    Validates document IDs against the UUID index and manages a shared
    ``selected_ids`` set that the caller can read after the conversation ends.
    """

    def _select_doc(add: str | None = None, remove: str | None = None) -> str:
        if add:
            if add not in uuid_index:
                return SELECTED_DOC_FAILURE_RESPONSE
            selected_ids.add(add)
            return SELECTED_DOC_SUCCESS_RESPONSE
        if remove:
            selected_ids.discard(remove)
            return SELECTED_DOC_REMOVAL_RESPONSE
        return SELECTED_DOC_FAILURE_RESPONSE

    return _select_doc


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent_for_question(
    question_id: str,
    question: str,
    llm: LLMInterface,
    system_prompt: str,
    uuid_index: dict[str, str],
    quiet: bool,
    model: str | None = None,
    reasoning_level: ReasoningLevel = "medium",
) -> dict[str, Any]:
    """Run the agentic loop for a single question.

    Returns a dict with keys: question_id, answer, document_ids
    """
    selected_ids: set[str] = set()

    run_executor, get_semaphore_wait = make_run_tool_executor(
        cwd=os.path.abspath(SOURCES_DIR),
    )
    select_doc_executor = make_select_doc_executor(uuid_index, selected_ids)
    read_tool = DocumentReadTool(
        base_dir=os.path.abspath(SOURCES_DIR),
        generated_doc_contents=True,
        include_dsid=True,
    )

    executors: dict[str, Any] = {
        RUN_TOOL_NAME: run_executor,
        READ_TOOL: read_tool.execute,
        SELECT_DOC_TOOL_NAME: select_doc_executor,
    }

    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=question),
    ]

    if not quiet:
        print(f"\n{'=' * 60}")
        print(f"Question {question_id}: {question}")
        print("=" * 60)

    # On timeout, a toolless LLM forces a text-only answer.
    force_finish_llm = get_llm(
        tools=None, quiet=True, reasoning_level=reasoning_level, model=model
    )

    # Context compaction: when messages exceed the char budget, summarise the
    # conversation with a cheap LLM instead of bluntly dropping old pairs.
    compaction_fn = make_context_compaction_fn(quiet=quiet, cheap_model=model)

    run_agent_conversation(
        llm=llm,
        executors=executors,
        messages=messages,
        timeout_seconds=QUESTION_TIMEOUT_SECONDS,
        shutdown_warning_seconds=30,
        shutdown_message=OUT_OF_TIME_USER_MESSAGE,
        force_finish_llm=force_finish_llm,
        force_finish_message=OUT_OF_TIME_USER_MESSAGE,
        parallel_tool_execution=True,
        tool_timeout=COMMAND_TIMEOUT_SECONDS + 10,
        quiet=quiet,
        context_compaction_fn=compaction_fn,
        deadline_credit_fn=get_semaphore_wait,
    )

    # The answer is the last assistant message (text-only = conversation end).
    answer = ""
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.content:
            answer = msg.content
            break

    # Document IDs come from the select_doc executor's accumulated state.
    document_ids = sorted(selected_ids)

    if not quiet and answer:
        print(f"\n[answer] {answer[:100]}... " f"document_ids={document_ids}")

    return {
        "question_id": question_id,
        "answer": answer,
        "document_ids": document_ids,
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_questions_jsonl(
    path: str,
    limit: int | None = None,
    question_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Load questions from a JSONL file, returning only question_id and question.

    If question_ids is provided, only those IDs are returned (in file order).
    """
    questions: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            qid = data["question_id"]
            if question_ids is not None and qid not in question_ids:
                continue
            questions.append({"question_id": qid, "question": data["question"]})
            if limit and len(questions) >= limit:
                break
    return questions


def load_subset_ids(path: str, per_type: int) -> set[str]:
    """Return the first `per_type` question IDs for each question_type."""
    type_counts: dict[str, int] = {}
    selected: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            qt = d.get("question_type", "unknown")
            count = type_counts.get(qt, 0)
            if count < per_type:
                selected.add(d["question_id"])
                type_counts[qt] = count + 1
    return selected


def load_existing_question_ids(path: str) -> set[str]:
    """Load question IDs already present in the output file."""
    ids: set[str] = set()
    if not os.path.exists(path):
        return ids
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ids.add(data["question_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def append_result(path: str, result: dict[str, Any], lock: threading.Lock) -> None:
    """Thread-safe wrapper around append_to_jsonl."""
    with lock:
        append_to_jsonl(path, result)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CLI agent to answer questions from the document corpus."
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of questions to process (default: all)",
    )
    parser.add_argument(
        "--subset-per-type",
        type=int,
        default=None,
        metavar="N",
        help="Only process the first N questions of each question_type",
    )
    parser.add_argument(
        "--questions-file",
        type=str,
        default=QUESTIONS_PATH,
        help=f"Path to questions JSONL (default: {QUESTIONS_PATH})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSONL path (default: answer_evaluation/answers_agent.jsonl)",
    )
    parser.add_argument(
        "--question-id",
        type=str,
        default=None,
        help="Process only this specific question ID",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already present in the output file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the LLM model name for all calls (default: LLM_MODEL_NAME env var)",
    )
    parser.add_argument(
        "--reasoning-level",
        type=str,
        default="medium",
        choices=["low", "medium", "high"],
        help="Reasoning effort level for the main LLM (default: medium)",
    )
    args = parser.parse_args()

    use_quiet = args.parallelism > 1

    # Pre-flight: verify all allowed shell commands are available
    missing = check_available_commands()
    if missing:
        print(
            f"Note: {len(missing)} command(s) not found on this system: "
            + ", ".join(sorted(missing))
        )
        print(
            "This is typically fine — it just gives the LLM slightly less "
            "flexibility when searching. It should not be very detrimental "
            "unless a large number of commands are missing."
        )
        if not confirm_yes_no("Proceed?", default=True):
            return

    questions_file = args.questions_file
    output_path = args.output or "answer_evaluation/answers_agent.jsonl"

    # Load UUID index for document ID validation by select_doc_by_dsid tool
    if os.path.exists(UUID_INDEX_PATH):
        if confirm_yes_no("Regenerate UUID index from disk?", default=True):
            uuid_index = rebuild_uuid_index()
        else:
            uuid_index = load_or_build_uuid_index()
    else:
        uuid_index = load_or_build_uuid_index()  # builds from scratch

    # Build LLM-facing artefacts *after* the preflight check has narrowed
    # _active_commands so they only reference available commands.
    system_prompt = build_system_prompt(corpus_size=len(uuid_index))
    # Schema-only read tool instance (per-question instances are created in
    # run_agent_for_question with their own read tracking state).
    read_tool_for_schema = DocumentReadTool(
        base_dir=os.path.abspath(SOURCES_DIR),
        generated_doc_contents=True,
        include_dsid=True,
    )
    tools = build_tools(read_tool_for_schema)

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Determine which question IDs to run
    subset_ids: set[str] | None = None
    if args.question_id:
        subset_ids = {args.question_id}
    elif args.subset_per_type is not None:
        subset_ids = load_subset_ids(questions_file, args.subset_per_type)
        if not use_quiet:
            print(
                f"Subset: {len(subset_ids)} questions ({args.subset_per_type} per type)"
            )

    questions = load_questions_jsonl(
        questions_file, limit=args.limit, question_ids=subset_ids
    )

    # Resume support
    if args.resume:
        existing_ids = load_existing_question_ids(output_path)
        questions = [q for q in questions if q["question_id"] not in existing_ids]
        if not use_quiet:
            print(f"Resuming: {len(questions)} questions remaining.")

    if not questions:
        print("No questions to process.")
        return

    total = len(questions)
    if not use_quiet:
        print(f"Processing {total} question(s) with parallelism={args.parallelism}")
        print(
            f"Subprocess slots: {_SUBPROCESS_SLOTS} (set AGENT_SUBPROCESS_SLOTS to override)"
        )
        print(f"Output: {output_path}")
        print(f"Time limit per question: {QUESTION_TIMEOUT_SECONDS}s")
        print()

    write_lock = threading.Lock()

    def process_one(q: dict[str, Any]) -> dict[str, Any]:
        llm = get_llm(
            tools=tools,
            quiet=use_quiet,
            reasoning_level=args.reasoning_level,
            model=args.model,
        )
        result = run_agent_for_question(
            question_id=q["question_id"],
            question=q["question"],
            llm=llm,
            system_prompt=system_prompt,
            uuid_index=uuid_index,
            quiet=use_quiet,
            model=args.model,
            reasoning_level=args.reasoning_level,
        )
        append_result(output_path, result, write_lock)
        return result

    if args.parallelism == 1:
        for q in questions:
            process_one(q)
    else:
        future_timeout = QUESTION_TIMEOUT_SECONDS + 60
        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {executor.submit(process_one, q): q for q in questions}
            with tqdm(total=total, desc="Answering") as pbar:
                for future in as_completed(futures):
                    try:
                        future.result(timeout=future_timeout)
                    except Exception as exc:
                        q = futures[future]
                        print(
                            f"\n[error] {q['question_id']} failed: {exc}",
                            flush=True,
                        )
                        append_result(
                            output_path,
                            {
                                "question_id": q["question_id"],
                                "answer": "",
                                "document_ids": [],
                            },
                            write_lock,
                        )
                    pbar.update(1)

    print(f"\nDone. Results written to: {output_path}")


if __name__ == "__main__":
    main()
