"""CLI agent script for answering questions by searching the document corpus.

Each question is answered by an agentic loop that uses a shell `run()` tool
and a `finish(answer, document_ids)` tool.  Results are written to a JSONL
file compatible with the evaluation harness.

Variants (--variant):
  full      — source types + filename examples + prescribed search order (default)
  structure — source types + filename examples, no prescribed order
  minimal   — corpus path + tool descriptions only, no structural hints
  v2        — minimal map only: corpus location + content_field_names fact +
               tool awareness + question variety note. No procedure, no source
               type listing. Tool layer: overflow mode + navigation error messages.
  v3        — v2plus baseline + tool-layer improvements per agent_vli_instructions.md:
               session cost footer (cmd #N, session elapsed), zero-result counter with
               subdirectory map, situation-aware jq null hints, path-list overflow
               detection, exact command repeat annotation, graceful shutdown at T-30s.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from src.llm.factory import get_cheap_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.paths import QUESTIONS_PATH, SOURCES_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_TIMEOUT_SECONDS = 300  # 5 minutes per question

VARIANTS = ("full", "structure", "minimal", "v2", "v2plus", "v3")

# Note added to all system prompt variants.
UNANSWERABLE_NOTE = (
    "Note: some questions may not have an answer in this corpus. "
    "If after thorough searching you are confident the information is not present, "
    "call `finish()` with a brief explanation as the answer "
    '(e.g. "This information is not available in the provided corpus") '
    "and an empty `document_ids` list."
)

# ---------------------------------------------------------------------------
# Overflow mode — Layer 2 presentation (agent_vli_instructions.md)
# ---------------------------------------------------------------------------

# Trigger: output exceeding these thresholds is saved to a temp file rather
# than silently discarded.  The agent receives the first OVERFLOW_SHOW_LINES
# lines plus a navigation pointer to the full file.
OVERFLOW_TRIGGER_LINES = 100
OVERFLOW_TRIGGER_BYTES = 20 * 1024  # 20 KB
OVERFLOW_SHOW_LINES = 100

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


# ---------------------------------------------------------------------------
# Presentation layer helpers (Technique 2 & 3 from agent_vli_instructions.md)
# ---------------------------------------------------------------------------

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
    """Extract the normalised base directory from an rg/grep command."""
    if not re.search(r"\b(rg|grep)\b", command):
        return None
    m = re.search(r"(generated_data/sources(?:/[\w\-]+)?)", command)
    if m:
        return os.path.normpath(m.group(1))
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
    return "Available subdirectories: " + "  ".join(f"sources/{d}/" for d in subdirs)


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


def _apply_presentation_layer(output: str, command: str = "") -> str:
    """Layer 2: process raw command output for LLM consumption.

    Mechanisms from agent_vli_instructions.md:
    - Situation-aware null hint  (Technique 2: different states → different messages)
    - Overflow mode              (map principle: preserve + pointer, don't discard)
    - Content-aware nav hint     (path-list overflow gets search hint, not grep hint)
    - Pass-through               (short output needs no transformation)
    """
    # Null detection: distinguish content_field_names null from any other field null.
    if output.strip() == "null":
        field = _extract_jq_field(command) if command else None
        if field and "content_field_names" in field:
            return (
                "null\n"
                "[hint: content_field_names not present — this may not be a corpus "
                "document; run jq 'keys' <file> to inspect structure]"
            )
        field_str = f" '{field}'" if field else ""
        return (
            "null\n"
            f"[hint: field{field_str} not found — check content_field_names for "
            "available content fields]"
        )

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)
    total_bytes = len(output.encode("utf-8", errors="replace"))

    if total_lines <= OVERFLOW_TRIGGER_LINES and total_bytes <= OVERFLOW_TRIGGER_BYTES:
        return output

    # Overflow mode: save full output to a navigable temp file.
    tmp_path = _next_overflow_path()
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(output)
    except OSError:
        truncated = "".join(lines[:OVERFLOW_SHOW_LINES])
        return truncated + f"\n[truncated: {total_lines} lines, {total_bytes} bytes]"

    shown = "".join(lines[:OVERFLOW_SHOW_LINES])

    # Content-aware navigation hint: path lists need search guidance, not grep-the-list.
    if _is_path_list(lines):
        subdirs = sorted(
            d
            for d in os.listdir(SOURCES_DIR)
            if os.path.isdir(os.path.join(SOURCES_DIR, d))
        )
        subdir_str = "  ".join(f"sources/{d}/" for d in subdirs)
        nav = (
            f"Search file contents: rg '<pattern>' {SOURCES_DIR}/\n"
            f"Scope by subdirectory: {subdir_str}"
        )
    else:
        nav = f"Navigate: grep '<pattern>' {tmp_path}  |  tail -n 50 {tmp_path}"

    return (
        shown + f"\n--- {total_lines} lines total ({total_bytes} bytes) ---\n"
        f"Full output saved: {tmp_path}\n"
        f"{nav}"
    )


# Allowed command names (whitelist for the shell tool)
ALLOWED_COMMANDS = {
    "rg",
    "grep",
    "ls",
    "cat",
    "head",
    "find",
    "xargs",
    "jq",
    "wc",
    "tail",
    "echo",
    "sort",
    "uniq",
    "cut",
    "awk",
    "tr",
    "sed",
    "printf",
}

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

RUN_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "run",
    "description": (
        "Execute a shell command and return its output. "
        "Supports piping (|), logical operators (&&, ||), and sequential execution (;). "
        "Allowed commands: rg, grep, ls, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed. "
        "All paths must be absolute or relative to the current working directory. "
        "The document corpus is at the path provided in your system prompt. "
        "Use rg for fast full-text search, jq for JSON field extraction, ls/find to explore structure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The shell command to execute. "
                    "Pipe chaining is supported, e.g. 'rg \"keyword\" path | jq .field'. "
                    "Keep commands targeted; avoid reading entire large directories."
                ),
            }
        },
        "required": ["command"],
    },
}

FINISH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "finish",
    "description": (
        "Submit the final answer to the question and end the research session. "
        "Call this when you are confident in your answer. "
        "document_ids should be the dataset_doc_uuid values from the JSON files you read."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The complete answer to the question.",
            },
            "document_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of dataset_doc_uuid values (format: dsid_XXXX) "
                    "from the documents that contain the answer."
                ),
            },
        },
        "required": ["answer", "document_ids"],
    },
}

TOOLS = [RUN_TOOL_SCHEMA, FINISH_TOOL_SCHEMA]

# ---------------------------------------------------------------------------
# System prompt builders
# ---------------------------------------------------------------------------


def _read_agents_md(source_dir: str) -> str | None:
    """Read agents.md for a source directory, return content or None."""
    agents_md_path = os.path.join(source_dir, "agents.md")
    if os.path.isfile(agents_md_path):
        try:
            with open(agents_md_path) as f:
                return f.read()
        except OSError:
            pass
    return None


def _extract_filename_example(agents_md: str) -> str:
    """Extract a filename example from agents.md content."""
    match = re.search(r"e\.?g\.?\W+([a-zA-Z0-9_\-]+\.json)", agents_md)
    if match:
        return match.group(1)
    return "*.json"


def _build_source_type_section(sources_dir: str) -> str:
    """Build a section listing available source types and their filename patterns."""
    if not os.path.isdir(sources_dir):
        return ""

    source_types = sorted(
        [
            d
            for d in os.listdir(sources_dir)
            if os.path.isdir(os.path.join(sources_dir, d))
        ]
    )

    if not source_types:
        return ""

    lines = ["## Available source types", ""]
    for st in source_types:
        source_path = os.path.join(sources_dir, st)
        agents_md = _read_agents_md(source_path)
        example = _extract_filename_example(agents_md) if agents_md else "*.json"
        lines.append(f"- `{st}/`  — filenames like `{example}`")

    return "\n".join(lines)


def _build_source_type_map(sources_dir: str) -> str:
    """Build a minimal source type listing — names only, no filename examples.

    This is Level 0 map injection per agent_vli_instructions.md: tell the agent
    what exists without prescribing how to use it.
    """
    if not os.path.isdir(sources_dir):
        return ""

    source_types = sorted(
        [
            d
            for d in os.listdir(sources_dir)
            if os.path.isdir(os.path.join(sources_dir, d))
        ]
    )

    if not source_types:
        return ""

    type_list = "  ".join(f"`{st}/`" for st in source_types)
    return f"## Source types\n{type_list}"


def build_full_prompt(sources_dir: str) -> str:
    """Variant A: source types + filename examples + prescribed search order."""
    source_section = _build_source_type_section(sources_dir)

    return f"""You are a research agent. Your job is to answer questions by searching \
a document corpus stored on disk.

## Corpus location
The documents are at: {sources_dir}/
Each document is a JSON file. The field `dataset_doc_uuid` holds the document's \
unique ID (format: dsid_XXXX).

{source_section}

## Search strategy (most efficient first)
1. **Explore structure**: `ls {sources_dir}` to see source types; \
`ls {sources_dir}/<type>/` to see subdirectories.
2. **Search by filename**: Many sources encode key identifiers in the filename \
(ticket keys for jira/linear, company names for hubspot, dates for fireflies/gmail, \
PR numbers for github). Use `find {sources_dir}/<type>/ -name "*keyword*"` before \
full-text search.
3. **Scoped full-text search**: `rg "keyword" {sources_dir}/<type>/` — always scope \
to the most relevant source type first. This is much faster than searching the whole corpus.
4. **Cross-source search as last resort**: `rg "keyword" {sources_dir}/` — only when \
you don't know which source contains the answer.
5. **Read files**: Use `jq '.' file.json | head -50` or `jq '.field' file.json` to \
extract specific fields. The `dataset_doc_uuid` field contains the document ID you need.

## Rules
- `document_ids` must be `dataset_doc_uuid` values (dsid_XXXX) from files you actually read.
- Prefer targeted `rg` searches over `cat` on large files.
- If output is truncated, narrow with `head -n 30`, `rg <pattern>`, or `jq '.<field>'`.
- You have {QUESTION_TIMEOUT_SECONDS} seconds per question. Be efficient.
- Do NOT guess — find the answer in the corpus before calling finish.
- {UNANSWERABLE_NOTE}
"""


def build_structure_prompt(sources_dir: str) -> str:
    """Variant D: source types + filename examples, no prescribed search order."""
    source_section = _build_source_type_section(sources_dir)

    return f"""You are a research agent. Your job is to answer questions by searching \
a document corpus stored on disk.

## Corpus location
The documents are at: {sources_dir}/
Each document is a JSON file. The field `dataset_doc_uuid` holds the document's \
unique ID (format: dsid_XXXX).

{source_section}

## Available search tools
- `rg "keyword" <path>` — fast full-text search across JSON files
- `ls <path>` / `find <path>` — explore directory structure or search by filename
- `jq '.field' file.json` — extract specific fields from a JSON file
- `head -n 50 file.json` — preview a file without reading it entirely

## Rules
- `document_ids` must be `dataset_doc_uuid` values (dsid_XXXX) from files you actually read.
- Prefer targeted searches over reading entire files.
- If output is truncated, narrow your search.
- You have {QUESTION_TIMEOUT_SECONDS} seconds per question.
- Do NOT guess — find the answer in the corpus before calling finish.
- {UNANSWERABLE_NOTE}
"""


def build_minimal_prompt(sources_dir: str) -> str:
    """Variant B: corpus path + tool descriptions only, no structural hints."""
    return f"""You are a research agent. Your job is to answer questions by searching \
a document corpus stored on disk.

## Corpus location
The documents are at: {sources_dir}/
Each document is a JSON file. The field `dataset_doc_uuid` holds the document's \
unique ID (format: dsid_XXXX).

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, cat, head, find, jq, wc, \
tail, sort, uniq, cut, awk, tr, sed
- `finish(answer=..., document_ids=[...])` — submit your final answer

## Rules
- `document_ids` must be `dataset_doc_uuid` values (dsid_XXXX) from files you actually read.
- Do NOT guess — find the answer in the corpus before calling finish.
- You have {QUESTION_TIMEOUT_SECONDS} seconds per question.
- {UNANSWERABLE_NOTE}
"""


def build_v2_prompt(sources_dir: str) -> str:
    """Variant v2: minimal map following agent_vli_instructions.md.

    Provides only what is map information (what exists and how it is structured),
    not procedure (how to search).  The tool layer handles navigation via overflow
    mode and error messages — the system prompt stays out of search strategy.
    """
    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Documents are at: {sources_dir}/
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array that lists which fields hold the document's text content — use this to know which fields to read.

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, cat, head, find, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `finish(answer=..., document_ids=[...])` — submit your final answer; `document_ids` must be `dataset_doc_uuid` values from documents you actually read

## Notes
Questions vary widely — some require a single fact, some require connecting information across multiple documents, some ask about conflicting information between sources, and some may have no answer in the corpus at all. If you are confident the answer is not present, call `finish()` with a brief explanation and an empty `document_ids` list.
"""


def build_v2plus_prompt(sources_dir: str) -> str:
    """Variant v2+: v2 + source type map (Level 0 injection).

    Adds the source type listing back as pure map information — what exists,
    not how to use it.  Fixes regressions on basic/completeness where the agent
    needs to know source types to scope searches, without reintroducing procedure.
    """
    source_map = _build_source_type_map(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Documents are at: {sources_dir}/
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array that lists which fields hold the document's text content — use this to know which fields to read.

{source_map}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, cat, head, find, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `finish(answer=..., document_ids=[...])` — submit your final answer; `document_ids` must be `dataset_doc_uuid` values from documents you actually read

## Notes
Questions vary widely — some require a single fact, some require connecting information across multiple documents, some ask about conflicting information between sources, and some may have no answer in the corpus at all. If you are confident the answer is not present, call `finish()` with a brief explanation and an empty `document_ids` list.
"""


def build_v3_prompt(sources_dir: str) -> str:
    """Variant v3: v2plus baseline; all improvements are in the tool layer.

    System prompt is identical to v2plus — source type map as Level 0 injection,
    no procedure.  The difference from v2plus is entirely in make_run_tool_executor:
    session cost footer, zero-result counter, situation-aware null hints,
    path-list overflow detection, exact repeat annotation, graceful shutdown.
    """
    return build_v2plus_prompt(sources_dir)


def build_system_prompt(sources_dir: str, variant: str = "full") -> str:
    """Build system prompt for the given variant."""
    if variant == "full":
        return build_full_prompt(sources_dir)
    elif variant == "structure":
        return build_structure_prompt(sources_dir)
    elif variant == "minimal":
        return build_minimal_prompt(sources_dir)
    elif variant == "v2":
        return build_v2_prompt(sources_dir)
    elif variant == "v2plus":
        return build_v2plus_prompt(sources_dir)
    elif variant == "v3":
        return build_v3_prompt(sources_dir)
    else:
        raise ValueError(f"Unknown variant '{variant}'. Choose from: {VARIANTS}")


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
    if cmd_name not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
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
        return (
            "[error] empty command — available: rg, grep, find, ls, cat, jq, "
            "head, tail, wc, sort, uniq, cut, awk, tr, sed",
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

        if _is_binary(stdout):
            elapsed = (time.monotonic() - t0) * 1000
            return (
                "[error] binary file detected. "
                "Use: head -c 100 <file> or jq '.<field>' <file> to inspect.",
                1,
                elapsed,
            )

        operator = seg.operator

        if operator == "|":
            stdin_data = stdout
            last_returncode = rc
            last_stdout = stdout
            i += 1
            continue

        if operator == "&&":
            last_stdout = stdout
            last_returncode = rc
            if rc != 0:
                combined = stdout + stderr
                elapsed = (time.monotonic() - t0) * 1000
                output = combined.decode("utf-8", errors="replace")
                return (output, rc, elapsed)
            stdin_data = None
            i += 1
            continue

        if operator == "||":
            last_stdout = stdout
            last_returncode = rc
            if rc == 0:
                break
            stdin_data = None
            i += 1
            continue

        if operator == ";":
            last_stdout = stdout
            last_returncode = rc
            stdin_data = None
            i += 1
            continue

        last_stdout = stdout
        last_returncode = rc
        if rc != 0 and stderr:
            last_stdout = stdout + b"\n[stderr] " + stderr
        break

    elapsed = (time.monotonic() - t0) * 1000
    decoded = last_stdout.decode("utf-8", errors="replace")
    return (decoded, last_returncode, elapsed)


# ---------------------------------------------------------------------------
# RunTool & FinishTool
# ---------------------------------------------------------------------------


class FinishSignal(Exception):
    """Raised when the agent calls finish()."""

    def __init__(self, answer: str, document_ids: list[str]) -> None:
        self.answer = answer
        self.document_ids = document_ids
        super().__init__(answer)


def make_run_tool_executor(
    cwd: str | None = None,
    session_start: float | None = None,
) -> Any:
    """Create a run tool executor with per-session state.

    Tracks per-session state for Technique 2 & 3 signals:
    - cmd index + session elapsed  → footer cost awareness
    - exact command history        → repeat annotation
    - zero-result counts per path  → subdirectory map hint after 5 misses
    """
    _t0 = session_start if session_start is not None else time.monotonic()
    _cmd_index = [0]
    _seen: dict[str, int] = {}  # command → first cmd index
    _zero_counts: dict[str, int] = {}  # normalised base path → consecutive zeros
    _subdirs_hint = _build_subdirs_hint(SOURCES_DIR)

    def _run(command: str) -> str:
        _cmd_index[0] += 1
        idx = _cmd_index[0]
        session_elapsed = time.monotonic() - _t0

        # Exact repeat detection (Technique 2: different state → different message)
        repeat_prefix = ""
        if command in _seen:
            repeat_prefix = (
                f"[note: identical to cmd #{_seen[command]} — result unchanged]\n"
            )
        else:
            _seen[command] = idx

        output, rc, elapsed_ms = execute_chain(command, cwd=cwd)

        # Zero-result counter — emit subdirectory map hint at threshold
        zero_hint = _update_and_get_zero_hint(
            _zero_counts, command, output, rc, _subdirs_hint
        )

        output = _apply_presentation_layer(output, command=command)

        # Technique 3: consistent footer with cmd index + session elapsed
        footer = f"[exit:{rc} | {elapsed_ms:.0f}ms | cmd #{idx} | session: {session_elapsed:.0f}s]"

        parts: list[str] = []
        if repeat_prefix:
            parts.append(repeat_prefix)
        parts.append(output)
        if zero_hint:
            parts.append(zero_hint)
        parts.append(footer)
        return "\n".join(parts)

    return _run


def make_finish_tool_executor() -> Any:
    def _finish(answer: str, document_ids: list[str]) -> str:
        raise FinishSignal(answer=answer, document_ids=document_ids)

    return _finish


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------

_MAX_CONTEXT_CHARS = 200_000


def _prune_messages(messages: list[Message]) -> list[Message]:
    """Drop the oldest tool_call/tool_result pairs when context is too large."""
    total_chars = sum(len(m.content or "") for m in messages)
    if total_chars <= _MAX_CONTEXT_CHARS:
        return messages

    header = messages[:2]
    history = messages[2:]

    while total_chars > _MAX_CONTEXT_CHARS and len(history) >= 2:
        if history[0].role == "tool_call" and history[1].role == "tool_result":
            dropped_chars = len(history[0].content or "") + len(
                history[1].content or ""
            )
            history = history[2:]
            total_chars -= dropped_chars
        else:
            total_chars -= len(history[0].content or "")
            history = history[1:]

    return header + history


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def run_agent_for_question(
    question_id: str,
    question: str,
    llm: LLMInterface,
    system_prompt: str,
    quiet: bool,
) -> dict[str, Any]:
    """Run the agentic loop for a single question.

    Returns a dict with keys:
        question_id, answer, document_ids,
        elapsed_seconds, iterations, commands_run, timed_out, llm_retries
    """
    start_time = time.monotonic()
    deadline = start_time + QUESTION_TIMEOUT_SECONDS

    run_executor = make_run_tool_executor(cwd=None, session_start=start_time)
    finish_executor = make_finish_tool_executor()

    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=question),
    ]

    if not quiet:
        print(f"\n{'=' * 60}")
        print(f"Question {question_id}: {question}")
        print("=" * 60)

    iteration = 0
    commands_run: list[str] = []
    llm_retries = 0
    _graceful_shutdown_injected = False

    def _make_result(
        answer: str, doc_ids: list[str], timed_out: bool
    ) -> dict[str, Any]:
        return {
            "question_id": question_id,
            "answer": answer,
            "document_ids": doc_ids,
            "elapsed_seconds": round(time.monotonic() - start_time, 2),
            "iterations": iteration,
            "commands_run": commands_run,
            "timed_out": timed_out,
            "llm_retries": llm_retries,
        }

    while time.monotonic() < deadline:
        # Graceful shutdown signal at T-30s (agent_vli_instructions.md: external mechanism,
        # not iteration limit — lets the agent wrap up on its own terms).
        if (
            not _graceful_shutdown_injected
            and (time.monotonic() - start_time) >= QUESTION_TIMEOUT_SECONDS - 30
        ):
            _graceful_shutdown_injected = True
            messages.append(
                Message(
                    role="user",
                    content=(
                        "[session ending in ~30s] Summarize your best current answer "
                        "based on what you've found so far."
                    ),
                )
            )

        iteration += 1
        full_response = ""
        tool_calls: list[ToolCall] = []

        messages = _prune_messages(messages)

        try:
            for chunk in llm.generate(messages):
                if isinstance(chunk, str):
                    full_response += chunk
                    if not quiet:
                        print(chunk, end="", flush=True)
                elif isinstance(chunk, ToolCall):
                    tool_calls.append(chunk)
        except Exception as llm_err:
            llm_retries += 1
            if not quiet:
                print(f"\n[warn] LLM error (will retry): {llm_err}", flush=True)
            time.sleep(5)
            continue

        if not quiet and full_response:
            print()

        if tool_calls:
            for tool_call in tool_calls:
                messages.append(
                    Message(role="tool_call", content="", tool_call=tool_call)
                )

                if not quiet:
                    print(
                        f"\n[Tool: {tool_call.name}] args={json.dumps(tool_call.args)}"
                    )

                try:
                    if tool_call.name == "run":
                        cmd = tool_call.args.get("command", "")
                        commands_run.append(cmd)
                        result = run_executor(**tool_call.args)
                    elif tool_call.name == "finish":
                        finish_executor(**tool_call.args)
                        result = "Done."
                    else:
                        result = (
                            f"[error] unknown tool '{tool_call.name}'. "
                            "Available tools: run, finish."
                        )
                except FinishSignal as sig:
                    if not quiet:
                        print(
                            f"\n[finish] answer={sig.answer[:100]}... "
                            f"document_ids={sig.document_ids}"
                        )
                    return _make_result(sig.answer, sig.document_ids, timed_out=False)

                if not quiet:
                    preview = result[:300].replace("\n", " ")
                    print(f"  -> {preview}")

                messages.append(
                    Message(
                        role="tool_result",
                        content=result,
                        call_id=tool_call.call_id,
                    )
                )
            continue

        # No tool calls — LLM stopped without calling a tool
        if full_response:
            messages.append(Message(role="assistant", content=full_response))
        break

    # Time limit (or no-tool break) reached without finish()
    timed_out = time.monotonic() >= deadline
    if not quiet:
        elapsed = time.monotonic() - start_time
        if timed_out:
            print(
                f"\n[warn] time limit ({QUESTION_TIMEOUT_SECONDS}s) reached "
                f"after {iteration} iteration(s) for {question_id} "
                f"(elapsed: {elapsed:.1f}s)"
            )
        else:
            print(f"\n[warn] agent stopped without finish() for {question_id}")

    return _make_result("", [], timed_out=timed_out)


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
    """Append a single result to the output JSONL file (thread-safe)."""
    line = json.dumps(result, ensure_ascii=False)
    with lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CLI agent to answer questions from the document corpus."
    )
    parser.add_argument(
        "--variant",
        choices=VARIANTS,
        default="full",
        help=(
            "System prompt variant: "
            "'full' (source types + filename hints + search order), "
            "'structure' (source types + filename hints, no order), "
            "'minimal' (corpus path + tool descriptions only). "
            "Default: full"
        ),
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
        "--output",
        type=str,
        default=None,
        help=(
            "Output JSONL path. "
            "Defaults to answer_evaluation/answers_variant_{variant}.jsonl"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already present in the output file",
    )
    args = parser.parse_args()

    use_quiet = args.parallelism > 1

    output_path = (
        args.output or f"answer_evaluation/answers_variant_{args.variant}.jsonl"
    )

    # Build system prompt once (discovers source types from disk)
    system_prompt = build_system_prompt(SOURCES_DIR, args.variant)

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Determine which question IDs to run
    subset_ids: set[str] | None = None
    if args.subset_per_type is not None:
        subset_ids = load_subset_ids(QUESTIONS_PATH, args.subset_per_type)
        if not use_quiet:
            print(
                f"Subset: {len(subset_ids)} questions ({args.subset_per_type} per type)"
            )

    questions = load_questions_jsonl(
        QUESTIONS_PATH, limit=args.limit, question_ids=subset_ids
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
        print(f"Variant: {args.variant}")
        print(f"Processing {total} question(s) with parallelism={args.parallelism}")
        print(f"Output: {output_path}")
        print(f"Time limit per question: {QUESTION_TIMEOUT_SECONDS}s")
        print()

    write_lock = threading.Lock()

    def process_one(q: dict[str, Any]) -> dict[str, Any]:
        llm = get_cheap_llm(tools=TOOLS, quiet=use_quiet, reasoning_level=None)
        result = run_agent_for_question(
            question_id=q["question_id"],
            question=q["question"],
            llm=llm,
            system_prompt=system_prompt,
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
            with tqdm(total=total, desc=f"[{args.variant}] Answering") as pbar:
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
                                "elapsed_seconds": QUESTION_TIMEOUT_SECONDS,
                                "iterations": 0,
                                "commands_run": [],
                                "timed_out": True,
                                "llm_retries": 0,
                            },
                            write_lock,
                        )
                    pbar.update(1)

    print(f"\nDone. Results written to: {output_path}")


if __name__ == "__main__":
    main()
