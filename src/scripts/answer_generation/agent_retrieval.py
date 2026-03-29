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
    --questions-file   Path to questions JSONL (default: generated_data/questions.jsonl)
    --output           Output JSONL path (default: answer_evaluation/answers_agent.jsonl)
    --question-id      Process only this specific question ID
    --resume           Skip questions already present in the output file
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from src.llm.auto_conversation import run_agent_conversation
from src.llm.factory import get_llm
from src.llm.interface import LLMInterface, Message
from src.paths import QUESTIONS_PATH, SOURCES_DIR
from src.utils.cli import confirm_yes_no
from src.utils.document_index import load_or_build_uuid_index, rebuild_uuid_index
from src.utils.questions import append_to_jsonl
from src.prompts.agent_retrieval_answer_gen import (
    AGENT_RETRIEVAL_SYSTEM_PROMPT,
    ALLOWED_COMMANDS,
    OUT_OF_TIME_USER_MESSAGE,
    RUN_TOOL_NAME,
    SELECT_DOC_TOOL_NAME,
    SELECT_DOC_TOOL_SCHEMA,
    SELECTED_DOC_FAILURE_RESPONSE,
    SELECTED_DOC_REMOVAL_RESPONSE,
    SELECTED_DOC_SUCCESS_RESPONSE,
    build_run_tool_schema,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_TIMEOUT_SECONDS = 600  # 10 minutes per question

# Layer 2 truncation limits — output is truncated at whichever is hit first.
TRUNCATION_MAX_LINES = 100
TRUNCATION_MAX_CHARS = 30_000

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

# Temp-file storage for full output when truncation occurs, so the agent can
# navigate the complete result with grep/tail.
_overflow_dir: str | None = None
_overflow_dir_lock = threading.Lock()
_overflow_counter: int = 0
_overflow_counter_lock = threading.Lock()


def _get_overflow_dir() -> str:
    global _overflow_dir
    with _overflow_dir_lock:
        if _overflow_dir is None:
            _overflow_dir = tempfile.mkdtemp(prefix="rag-agent-")
    return _overflow_dir


def _next_overflow_path() -> str:
    global _overflow_counter
    with _overflow_counter_lock:
        _overflow_counter += 1
        n = _overflow_counter
    return os.path.join(_get_overflow_dir(), f"cmd-{n}.txt")


_PATH_LINE_RE = re.compile(r"^[./][\w/\-._]+\.(json|md|txt|yaml|yml)\s*$")


def _is_path_list(lines: list[str], sample_size: int = 50) -> bool:
    """Return True if >80% of sampled lines look like file paths."""
    sample = [ln.rstrip("\n") for ln in lines[:sample_size]]
    if not sample:
        return False
    return sum(1 for ln in sample if _PATH_LINE_RE.match(ln)) / len(sample) > 0.8


def _extract_jq_field(command: str) -> str | None:
    """Extract the primary jq field path from a command string."""
    m = re.search(r"\bjq\b[^|&;]*?['\"](\.[^\"'|\s]+)['\"]", command)
    if m:
        return m.group(1)
    m = re.search(r"\bjq\b\s+(?:-r\s+)?(\.[^\s|&;\"']+)", command)
    if m:
        return m.group(1)
    return None


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
    whichever is hit first), context-aware hints for null/jq results, and
    saves full output to a navigable temp file when truncated.

    Returns:
        (formatted_output, truncation_line) where truncation_line is empty
        if no truncation occurred, or a ``--- output truncated ... ---``
        string to insert before the footer.
    """
    # Null detection: context-aware hint for jq null results.
    if output.strip() == "null":
        field = _extract_jq_field(command) if command else None
        if field and "content_field_names" in field:
            return (
                "null\n"
                "[hint: content_field_names not present — this may not be a corpus "
                "document; run jq 'keys' <file> to inspect structure]",
                "",
            )
        field_str = f" '{field}'" if field else ""
        return (
            "null\n"
            f"[hint: field{field_str} not found — check content_field_names for "
            "available content fields]",
            "",
        )

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)
    total_chars = len(output)

    # Check if truncation is needed
    truncated_by_lines = total_lines > TRUNCATION_MAX_LINES
    truncated_by_chars = total_chars > TRUNCATION_MAX_CHARS

    if not truncated_by_lines and not truncated_by_chars:
        return output, ""

    # Save full output to a temp file for agent navigation
    tmp_path: str | None = None
    try:
        p = _next_overflow_path()
        with open(p, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(output)
        tmp_path = p
    except OSError:
        pass

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

    # Navigation hint for the full output
    if tmp_path is not None:
        if _is_path_list(lines):
            abs_sources = os.path.abspath(SOURCES_DIR)
            subdirs = sorted(
                d
                for d in os.listdir(abs_sources)
                if os.path.isdir(os.path.join(abs_sources, d))
            )
            subdir_str = "  ".join(f"{d}/" for d in subdirs)
            nav = (
                f"Search file contents: grep '<pattern>' .\n"
                f"Scope by subdirectory: {subdir_str}"
            )
        else:
            nav = f"Full output: {tmp_path}\nNavigate: grep '<pattern>' {tmp_path}  |  tail -n 50 {tmp_path}"
        truncation_line += f"\n{nav}"

    return shown, truncation_line


# ---------------------------------------------------------------------------
# System prompt & tool schemas (built dynamically from _active_commands)
# ---------------------------------------------------------------------------


def build_tools() -> list[dict[str, Any]]:
    """Build the tool schema list with the current active command set."""
    return [
        build_run_tool_schema(_active_commands),
        SELECT_DOC_TOOL_SCHEMA,
    ]


def build_system_prompt() -> str:
    """Build the system prompt by formatting the template with active commands."""
    allowed_list = ", ".join(sorted(_active_commands))
    return AGENT_RETRIEVAL_SYSTEM_PROMPT.format(allowed_commands=allowed_list)


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
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - t0) * 1000
            return (
                "[error] command timed out after 60 seconds. "
                "Pipe with `| head -N` to limit output volume.",
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
                "[error] binary file detected. "
                "Use: head -c 100 <file> or jq '.<field>' <file> to inspect.",
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
) -> Any:
    """Create a run tool executor with per-session state.

    Tracks per-session state for Layer 2 presentation signals:
    - cmd index + session elapsed  → metadata footer
    - exact command history        → repeat-command annotation
    - zero-result counts per path  → subdirectory navigation hint after 5 misses
    """
    _t0 = session_start if session_start is not None else time.monotonic()
    _cmd_index = [0]
    _seen: dict[str, int] = {}  # command → first cmd index
    _zero_counts: dict[str, int] = {}  # normalised base path → consecutive zeros
    _subdirs_hint = _build_subdirs_hint(os.path.abspath(SOURCES_DIR))

    def _run(command: str) -> str:
        _cmd_index[0] += 1
        idx = _cmd_index[0]
        session_elapsed = time.monotonic() - _t0

        # --- Layer 1: execute the command chain (raw, unmodified output) ---
        output, rc, elapsed_ms = execute_chain(command, cwd=cwd)

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

        # Truncation, null hints, overflow file
        output, truncation_line = _format_tool_output(output, command=command)

        # Metadata footer
        footer = f"[exit:{rc} | {elapsed_ms:.0f}ms | cmd #{idx} | session: {session_elapsed:.0f}s]"

        # Assemble final result: output → hints → truncation → footer
        parts: list[str] = []
        if repeat_prefix:
            parts.append(repeat_prefix)
        parts.append(output)
        if zero_hint:
            parts.append(zero_hint)
        if truncation_line:
            parts.append(truncation_line)
        parts.append(footer)
        return "\n".join(parts)

    return _run


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
) -> dict[str, Any]:
    """Run the agentic loop for a single question.

    Returns a dict with keys: question_id, answer, document_ids
    """
    selected_ids: set[str] = set()

    run_executor = make_run_tool_executor(
        cwd=os.path.abspath(SOURCES_DIR),
    )
    select_doc_executor = make_select_doc_executor(uuid_index, selected_ids)

    executors: dict[str, Any] = {
        RUN_TOOL_NAME: run_executor,
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
    force_finish_llm = get_llm(tools=None, quiet=True, reasoning_level=None)

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
        quiet=quiet,
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
    args = parser.parse_args()

    use_quiet = args.parallelism > 1

    # Pre-flight: verify all allowed shell commands are available
    missing = check_available_commands()
    if missing:
        print("Warning: the following commands are not available on this system:")
        for cmd in missing:
            print(f"  - {cmd}")
        if not confirm_yes_no("Proceed anyway?", default=False):
            return

    questions_file = args.questions_file
    output_path = args.output or "answer_evaluation/answers_agent.jsonl"

    # Load UUID index for document ID validation by select_doc_by_dsid tool
    if os.path.exists("generation_cache/uuid_index.json"):
        if confirm_yes_no("Regenerate UUID index from disk?", default=True):
            uuid_index = rebuild_uuid_index()
        else:
            uuid_index = load_or_build_uuid_index()
    else:
        uuid_index = load_or_build_uuid_index()  # builds from scratch

    # Build LLM-facing artefacts *after* the preflight check has narrowed
    # _active_commands so they only reference available commands.
    system_prompt = build_system_prompt()
    tools = build_tools()

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
        print(f"Output: {output_path}")
        print(f"Time limit per question: {QUESTION_TIMEOUT_SECONDS}s")
        print()

    write_lock = threading.Lock()

    def process_one(q: dict[str, Any]) -> dict[str, Any]:
        llm = get_llm(tools=tools, quiet=use_quiet, reasoning_level=None)
        result = run_agent_for_question(
            question_id=q["question_id"],
            question=q["question"],
            llm=llm,
            system_prompt=system_prompt,
            uuid_index=uuid_index,
            quiet=use_quiet,
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
