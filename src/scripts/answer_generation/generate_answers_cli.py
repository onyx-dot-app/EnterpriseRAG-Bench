"""CLI agent script for answering questions by searching the document corpus.

Each question is answered by an agentic loop that uses a shell run() tool, a
select_doc_by_dsid() tool for incrementally tracking relevant documents, and a
finish(answer) tool. Document IDs are validated against the UUID index at selection
time to prevent hallucination. Results are written to a JSONL file compatible
with the evaluation harness. Multiple system prompt variants control how much
structural information is provided to the agent.

Usage:
    python -m src.scripts.answer_generation.generate_answers_cli [OPTIONS]

Args:
    --variant          System prompt variant (default: "full")
                         full      - source types + filename examples + prescribed search order
                         structure - source types + filename examples, no prescribed order
                         minimal   - corpus path + tool descriptions only, no structural hints
                         v2        - minimal map with tool awareness, no source type listing
                         v3        - v2 baseline + tool-layer improvements (cost footer,
                                     zero-result counter, jq hints, overflow detection)
    --parallelism      Number of parallel workers (default: 1)
    --limit            Maximum number of questions to process
    --subset-per-type  Only process first N questions of each question_type
    --output           Output JSONL path (default: answer_evaluation/answers_variant_{variant}.jsonl)
    --resume           Skip questions already present in the output file
    --questions        Path to a JSONL questions file (default: generated_data/questions.jsonl)
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
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tqdm import tqdm

from src.llm.factory import get_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.paths import QUESTIONS_PATH, SOURCES_DIR
from src.tools import READ_TOOL
from src.tools.tool_implementations.document_read import DocumentReadTool
from src.utils.document_index import load_or_build_uuid_index

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_TIMEOUT_SECONDS = 300  # 5 minutes per question

VARIANTS = (
    "full",
    "structure",
    "minimal",
    "v2",
    "v2plus",
    "v3",
    "v4",
    "v4plus",
    "v5",
    "v6",
    "v7",
    "v7plus",
    "v8",
    "v9",
)

HIGH_RESULT_THRESHOLD = 50

# Variants that use V6_TOOLS (select_doc_by_dsid only, no finish()).
# Update here when adding a new variant — drives tool selection in process_one.
_V6_TOOL_VARIANTS: frozenset[str] = frozenset({"v6", "v7", "v7plus", "v8", "v9"})

# Variants where agent cwd is set to SOURCES_DIR (relative-path mode).
# Update here when adding a new variant — drives cwd selection in process_one.
_RELATIVE_CWD_VARIANTS: frozenset[str] = frozenset({"v7", "v7plus", "v8", "v9"})

# Global zero-result hint thresholds (consecutive zero-result searches across all paths).
_GLOBAL_ZERO_WARN = 8
_GLOBAL_ZERO_STRONG = 15

# Note added to all system prompt variants.
UNANSWERABLE_NOTE = (
    "Note: some questions may not have an answer in this corpus. "
    "If after thorough searching you are confident the information is not present, "
    "call `finish()` with a brief explanation as the answer "
    '(e.g. "This information is not available in the provided corpus").'
)

OUT_OF_TIME_USER_MESSAGE = (
    "You have run out of time to run further research. "
    "Please output your final answer now with the information you have gathered. "
    "If you have not found an answer, state that clearly."
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

_PATH_LINE_RE = re.compile(r"^[\w./][\w/\-._]*\.(json|md|txt|yaml|yml)\s*$")


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
    # Fallback: match a leading word-token path like `jira/` or `confluence/`
    m2 = re.search(r"\s([\w\-]+)/", command)
    if m2:
        return m2.group(1) + "/"
    # Whole-corpus search: rg "term" . or rg "term" (no path = cwd)
    if re.search(r"\s\./?(?:\s|$)", command) or not re.search(r"\s[\w./]", command):
        return "."
    return None


def _build_subdirs_hint(sources_dir: str, relative: bool = False) -> str:
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
    if relative:
        return "Available subdirectories: " + "  ".join(f"{d}/" for d in subdirs)
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


def _extract_search_term(command: str) -> str | None:
    """Extract the primary search pattern from an rg/grep command string."""
    # Match quoted pattern: rg "term" or rg 'term'
    m = re.search(r'\b(?:rg|grep)\b\s+(?:-\S+\s+)*["\']([^"\']+)["\']', command)
    if m:
        return m.group(1)
    # Match unquoted pattern: rg term path
    m = re.search(r"\b(?:rg|grep)\b\s+(?:-\S+\s+)*(\S+)", command)
    if m:
        return m.group(1)
    return None


def _get_high_result_hint(
    command: str,
    raw_output: str,
    rc: int,
    subdirs_hint: str,
    sources_dir: str | None = None,
    threshold: int = HIGH_RESULT_THRESHOLD,
) -> str:
    """Return hint when a path-list search returns too many results (Technique 2).

    When the search scope is the whole corpus (base == "."), emits concrete
    per-subdirectory example commands so the agent knows exactly what to try
    next rather than just being told to narrow down.
    """
    if rc != 0:
        return ""
    base = _extract_search_base_path(command)
    if base is None:
        return ""
    lines = [ln for ln in raw_output.strip().splitlines() if ln.strip()]
    if not (_is_path_list(lines) and len(lines) >= threshold):
        return ""

    count = len(lines)

    # When searching the whole corpus, generate concrete per-subdir suggestions
    if base in (".", "") and sources_dir and os.path.isdir(sources_dir):
        subdirs = sorted(
            d
            for d in os.listdir(sources_dir)
            if os.path.isdir(os.path.join(sources_dir, d))
        )
        term = _extract_search_term(command)
        if term and subdirs:
            examples = "  ".join(f'rg "{term}" {d}/ -l' for d in subdirs)
            return (
                f"[note: {count}+ matches — search too broad. "
                f"Scope to a subdirectory:\n  {examples}]"
            )

    note = (
        f"[note: {count}+ matches in {base} — search too broad. "
        "Use a more specific term or scope to a subdirectory.]"
    )
    return f"{note}\n{subdirs_hint}" if subdirs_hint else note


def _apply_presentation_layer(
    output: str, command: str = "", cwd: str | None = None
) -> str:
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
        _is_relative_cwd = cwd is not None and os.path.normpath(
            cwd
        ) == os.path.normpath(os.path.abspath(SOURCES_DIR))
        if _is_relative_cwd:
            subdir_str = "  ".join(f"{d}/" for d in subdirs)
            nav = (
                f"Search file contents: rg '<pattern>' .\n"
                f"Scope by subdirectory: {subdir_str}"
            )
        else:
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


# ---------------------------------------------------------------------------
# Progressive --help discovery (agent_vli_instructions.md Technique 1)
#
# Level 1: bare command with no args  → corpus-specific one-screen usage
# Level 2: command + partial args     → specific missing-parameter guidance
#
# Both return [usage] strings (exit:1) so the agent treats them as correctable
# errors and immediately knows what to do next — Technique 2 (error as nav).
# Interception happens in Python before the shell is invoked (Layer 2 boundary).
# ---------------------------------------------------------------------------

_S = "generated_data/sources"  # shorthand used in usage strings

_LEVEL1: dict[str, str] = {
    "rg": (
        f'[usage] rg: rg "<pattern>" <path> [flags]\n'
        f'  All docs:       rg "keyword" {_S}/\n'
        f'  Scoped:         rg "keyword" {_S}/<type>/\n'
        f'  Filenames only: rg "keyword" {_S}/ -l\n'
        f'  With context:   rg "keyword" {_S}/ -A 5 -B 2\n'
        f'  Case-insensitive: rg "keyword" {_S}/ -i'
    ),
    "jq": (
        "[usage] jq: jq \"<filter>\" <file>   (or pipe: cat file | jq '<filter>')\n"
        "  List fields:    jq 'keys' file.json\n"
        "  Content fields: jq '.content_field_names' file.json\n"
        "  Extract field:  jq '.<field>' file.json\n"
        "  Full doc:       jq '.' file.json"
    ),
    "find": (
        f'[usage] find: find <dir> -name "<pattern>"\n'
        f'  List corpus:    find {_S} -name "*.json"\n'
        f'  By source type: find {_S}/<type>/ -name "*.json"\n'
        f'  By name:        find {_S} -name "*keyword*"'
    ),
    "cat": (
        "[usage] cat: cat <file>   (use with pipe for large files)\n"
        "  Read file:      cat file.json\n"
        "  With jq:        cat file.json | jq '.<field>'\n"
        "  List fields:    cat file.json | jq 'keys'"
    ),
    "ls": (
        f"[usage] ls: ls <path>\n"
        f"  Source types:   ls {_S}/\n"
        f"  Type contents:  ls {_S}/<type>/\n"
        f"  Subdirs:        ls {_S}/<type>/<subdir>/"
    ),
    "grep": (
        '[usage] grep: grep "<pattern>" <file>   (for multi-file search, prefer rg)\n'
        '  In file:        grep -i "keyword" file.json\n'
        '  With context:   grep -A 5 -B 2 "keyword" file.json\n'
        '  Invert:         grep -v "keyword" file.json'
    ),
    "head": (
        "[usage] head: head -n <N> <file>\n"
        "  Preview:        head -n 50 file.json\n"
        "  Usually better: cat file.json | jq '.'"
    ),
    "tail": (
        "[usage] tail: tail -n <N> <file>\n"
        "  Last N lines:   tail -n 50 file.json\n"
        "  Overflow file:  tail -n 50 /tmp/rag-agent-*/cmd-N.txt"
    ),
    "wc": (
        "[usage] wc: wc -l <file>   (count lines)\n"
        "  Count docs:     find generated_data/sources -name '*.json' | wc -l\n"
        '  Count results:  rg "keyword" generated_data/sources/ -l | wc -l'
    ),
}

# Level 2: command + partial but insufficient args → specific parameter guidance.
# Each entry: (min_meaningful_tokens, hint).  Tokens = non-flag args after cmd name.
_LEVEL2: dict[str, tuple[int, str]] = {
    "rg": (
        2,
        f"[usage] rg needs a pattern AND a path\n"
        f"  Got pattern only — add path:\n"
        f'  rg "<pattern>" {_S}/          ← all docs\n'
        f'  rg "<pattern>" {_S}/<type>/   ← scoped',
    ),
    "jq": (
        2,
        "[usage] jq needs a filter AND a file (or pipe input)\n"
        "  Got filter only — add file or pipe:\n"
        "  jq '.<field>' file.json\n"
        "  cat file.json | jq '.<field>'",
    ),
}


def _count_positional_args(command: str) -> int:
    """Count non-flag tokens after the command name (approximation for Level 2)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return 0
    # Skip command name and any tokens starting with '-'
    return sum(1 for t in tokens[1:] if not t.startswith("-"))


def _progressive_help(command: str) -> str | None:
    """Return Level 1 or Level 2 usage hint, or None if the command looks complete."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    cmd_name = os.path.basename(tokens[0])

    # Level 1: bare command, no arguments at all
    if len(tokens) == 1 and cmd_name in _LEVEL1:
        return _LEVEL1[cmd_name]

    # Level 2: command has args but fewer positional args than minimum
    if cmd_name in _LEVEL2:
        min_pos, hint = _LEVEL2[cmd_name]
        if _count_positional_args(command) < min_pos:
            return hint

    return None


# Allowed command names (whitelist for the shell tool)
ALLOWED_COMMANDS = {
    "rg",
    "grep",
    "ls",
    "tree",
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

# Sorted, comma-separated list derived from ALLOWED_COMMANDS — used in tool schema
# and error messages so they stay in sync automatically.
_ALLOWED_CMDS_STR = ", ".join(sorted(ALLOWED_COMMANDS))

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

RUN_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "run",
    "description": (
        "Execute a shell command and return its output. "
        "Supports piping (|), logical operators (&&, ||), and sequential execution (;). "
        f"Allowed commands: {_ALLOWED_CMDS_STR}. "
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
                    "Pipe chaining is supported (|, &&, ;). "
                    "Do not use | head on search commands — the system handles large output automatically. "
                    "Keep searches targeted to avoid broad matches."
                ),
            }
        },
        "required": ["command"],
    },
}

SELECT_DOC_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "select_doc_by_dsid",
    "description": (
        "Add or remove a document from your answer list. "
        "Call this as you discover relevant documents during research — do not wait until the end. "
        "Document IDs are the dataset_doc_uuid values from JSON files you read. "
        "Invalid IDs are rejected immediately. "
        "Use 'add' to include a document and 'remove' to exclude a previously added one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "add": {
                "type": "string",
                "description": (
                    "The dataset_doc_uuid (format: dsid_ followed by a UUID) of the document to add."
                ),
            },
            "remove": {
                "type": "string",
                "description": (
                    "The dataset_doc_uuid (format: dsid_ followed by a UUID) of the document to remove."
                ),
            },
        },
    },
}

FINISH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "finish",
    "description": (
        "Submit the final answer to the question and end the research session. "
        "Call this when you are confident in your answer. "
        "Document IDs are tracked separately via select_doc_by_dsid — do not include them here."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The complete answer to the question.",
            },
        },
        "required": ["answer"],
    },
}

TOOLS = [RUN_TOOL_SCHEMA, SELECT_DOC_TOOL_SCHEMA, FINISH_TOOL_SCHEMA]

# v6: no finish() tool — agent ends by outputting plain text
V6_TOOLS = [RUN_TOOL_SCHEMA, SELECT_DOC_TOOL_SCHEMA]

# v9: v6 tools + read tool (DocumentReadTool schema, instantiated per question)
# Schema is built at runtime from DocumentReadTool.get_schema(); stored here as sentinel.
_READ_TOOL_SCHEMA_SENTINEL = READ_TOOL  # replaced with real schema in process_one

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


def _build_source_type_map_as_executed(sources_dir: str) -> str:
    """Format the source type listing as if `ls -1` was already run at session start.

    This signals to the agent that structure is already known — no need to
    re-run find/ls to discover it.  Reads agents.md dynamically so only present
    source types appear.

    Format mimics shell output:
        $ ls generated_data/sources/
        confluence/   fireflies/   github/   ...

        $ ls generated_data/sources/jira/
        int-requests/   misc-requests/   ops-requests/
    """
    if not os.path.isdir(sources_dir):
        return ""

    source_types = sorted(
        d
        for d in os.listdir(sources_dir)
        if os.path.isdir(os.path.join(sources_dir, d))
    )
    if not source_types:
        return ""

    # Top-level listing
    type_cols = "   ".join(f"{st}/" for st in source_types)
    lines = [
        f"## Corpus structure (already explored at session start)",
        f"",
        f"$ ls {sources_dir}/",
        type_cols,
    ]

    # Per-type: subdirectory listing + description + filename example
    for st in source_types:
        source_path = os.path.join(sources_dir, st)
        agents_md = _read_agents_md(source_path)
        description = _extract_first_content_rule(agents_md) if agents_md else None
        example = _extract_filename_example(agents_md) if agents_md else "*.json"

        subdirs = sorted(
            d
            for d in os.listdir(source_path)
            if os.path.isdir(os.path.join(source_path, d))
        )
        subdir_str = "   ".join(f"{d}/" for d in subdirs) if subdirs else "(flat)"

        lines.append(f"")
        lines.append(f"$ ls {sources_dir}/{st}/")
        lines.append(subdir_str)
        if description:
            lines.append(f"# {description}; filenames like {example}")

    return "\n".join(lines)


def _extract_first_content_rule(agents_md: str) -> str | None:
    """Extract the first bullet under 'Content rules:' from agents.md."""
    in_rules = False
    for line in agents_md.splitlines():
        if re.match(r"^Content rules:", line):
            in_rules = True
            continue
        if in_rules:
            stripped = line.strip()
            if stripped.startswith("- "):
                return stripped[2:].strip()
            # Skip blank lines
            if stripped:
                # Hit a non-bullet non-blank line — stop
                break
    return None


def _build_source_type_map_with_descriptions(sources_dir: str) -> str:
    """Build a source type map with one-line descriptions from agents.md.

    Each line: `<type>/`  — <first content rule>; filenames: `<example>`

    This is Level 0 map injection: tells the agent what each source type contains
    without prescribing search procedure.  Reads agents.md dynamically so only
    present source types appear.
    """
    if not os.path.isdir(sources_dir):
        return ""

    source_types = sorted(
        d
        for d in os.listdir(sources_dir)
        if os.path.isdir(os.path.join(sources_dir, d))
    )
    if not source_types:
        return ""

    lines = ["## Source types", ""]
    for st in source_types:
        source_path = os.path.join(sources_dir, st)
        agents_md = _read_agents_md(source_path)
        description = _extract_first_content_rule(agents_md) if agents_md else None
        example = _extract_filename_example(agents_md) if agents_md else "*.json"
        desc_str = f" — {description}" if description else ""
        lines.append(f"- `{st}/`{desc_str}; filenames like `{example}`")

    return "\n".join(lines)


def _build_source_type_map_relative(sources_dir: str) -> str:
    """Format the source type listing using relative paths (cwd=SOURCES_DIR).

    Mirrors _build_source_type_map_as_executed but uses `$ ls` (no path) and
    `$ ls jira/` (relative) instead of `$ ls generated_data/sources/` etc.
    """
    if not os.path.isdir(sources_dir):
        return ""

    source_types = sorted(
        d
        for d in os.listdir(sources_dir)
        if os.path.isdir(os.path.join(sources_dir, d))
    )
    if not source_types:
        return ""

    # Top-level listing (relative: just ls, no path argument)
    type_cols = "   ".join(f"{st}/" for st in source_types)
    lines = [
        "## Corpus structure (already explored at session start)",
        "",
        "$ ls",
        type_cols,
    ]

    # Per-type: subdirectory listing + description + filename example
    for st in source_types:
        source_path = os.path.join(sources_dir, st)
        agents_md = _read_agents_md(source_path)
        description = _extract_first_content_rule(agents_md) if agents_md else None
        example = _extract_filename_example(agents_md) if agents_md else "*.json"

        subdirs = sorted(
            d
            for d in os.listdir(source_path)
            if os.path.isdir(os.path.join(source_path, d))
        )
        subdir_str = "   ".join(f"{d}/" for d in subdirs) if subdirs else "(flat)"

        lines.append("")
        lines.append(f"$ ls {st}/")
        lines.append(subdir_str)
        if description:
            lines.append(f"# {description}; filenames like {example}")

    return "\n".join(lines)


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
- Use `select_doc_by_dsid(add=...)` to record relevant documents as you find them — do not wait until finish.
- `dataset_doc_uuid` values (dsid_XXXX) are validated immediately; invalid IDs are rejected.
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
- `ls <path>` / `find <path>` / `tree <path>` — explore directory structure or search by filename
- `jq '.field' file.json` — extract specific fields from a JSON file
- `head -n 50 file.json` — preview a file without reading it entirely

## Rules
- Use `select_doc_by_dsid(add=...)` to record relevant documents as you find them.
- `dataset_doc_uuid` values (dsid_XXXX) are validated immediately; invalid IDs are rejected.
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
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you find it
- `finish(answer=...)` — submit your final answer

## Rules
- Use `select_doc_by_dsid` to track relevant documents as you find them — do not wait until finish.
- `dataset_doc_uuid` values (dsid_XXXX) are validated immediately; invalid IDs are rejected.
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
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you find it; IDs are validated immediately
- `finish(answer=...)` — submit your final answer

## Notes
Questions vary widely — some require a single fact, some require connecting information across multiple documents, some ask about conflicting information between sources, and some may have no answer in the corpus at all. If you are confident the answer is not present, call `finish()` with a brief explanation and no documents selected.
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
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you find it; IDs are validated immediately
- `finish(answer=...)` — submit your final answer

## Notes
Questions vary widely — some require a single fact, some require connecting information across multiple documents, some ask about conflicting information between sources, and some may have no answer in the corpus at all. If you are confident the answer is not present, call `finish()` with a brief explanation and no documents selected.
"""


def build_v3_prompt(sources_dir: str) -> str:
    """Variant v3: v2plus baseline; all improvements are in the tool layer.

    System prompt is identical to v2plus — source type map as Level 0 injection,
    no procedure.  The difference from v2plus is entirely in make_run_tool_executor:
    session cost footer, zero-result counter, situation-aware null hints,
    path-list overflow detection, exact repeat annotation, graceful shutdown.
    """
    return build_v2plus_prompt(sources_dir)


def build_v4_prompt(sources_dir: str) -> str:
    """Variant v4: v3 tool layer + richer Level 0 map.

    Improvements over v3:
    - Dynamic source type descriptions from agents.md (what each type contains)
    - Session budget stated explicitly (agent knows its time horizon)
    - Expanded question variety note (terminology mismatch, single_doc patterns)

    No procedure injected — tool layer (progressive help, overflow, error nav) handles
    search strategy as per agent_vli_instructions.md.
    """
    source_map = _build_source_type_map_with_descriptions(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Documents are at: {sources_dir}/
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array that lists which fields hold the document's text content — use this to know which fields to read.

{source_map}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you find it; IDs are validated immediately
- `finish(answer=...)` — submit your final answer

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Notes
Questions vary widely in type and difficulty:
- **Single-document**: the answer is in one document; find it efficiently.
- **Multi-document / completeness**: the answer requires connecting facts across several documents.
- **Conflicting sources**: two sources may disagree; surface both sides.
- **No answer**: the corpus may not contain the answer at all — call `finish()` with a brief explanation and no documents selected.
- **Terminology mismatch**: the question may use different words than the documents (e.g. "cost" vs "price", "team lead" vs "manager"). Try synonyms and broader terms when an exact search returns nothing.
"""


def build_v4plus_prompt(sources_dir: str) -> str:
    """Variant v4plus: v4 tool layer + corpus structure as already-executed output.

    Key change from v4: the source type map is formatted as shell output that
    was already run at session start — including per-type subdirectory listings.
    This signals to the agent that structure is known and eliminates the
    warmup `find ... | head -20` pattern seen in v4 (17/30 questions).

    Also adds global zero-result counter (tool layer) and 10-minute budget.
    """
    structure = _build_source_type_map_as_executed(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Documents are at: {sources_dir}/
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array listing which fields hold text content — check this before reading field values.

{structure}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you find it; IDs are validated immediately
- `finish(answer=...)` — submit your final answer

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Notes
Questions vary widely in type and difficulty:
- **Single-document**: the answer is in one document; find it efficiently.
- **Multi-document / completeness**: the answer requires connecting facts across several documents.
- **Conflicting sources**: two sources may disagree; surface both sides.
- **No answer**: the corpus may not contain the answer — call `finish()` with a brief explanation and no documents selected.
- **Terminology mismatch**: the question may use different words than the documents. Try synonyms and broader terms when an exact search returns nothing.
"""


def build_v6_prompt(sources_dir: str) -> str:
    """v6: no finish() tool — agent ends by outputting plain text.

    Mirrors agent_retrieval.py architecture: select_doc_by_dsid accumulates docs
    incrementally, conversation ends with a text-only response (no tool call).
    Uses v4plus already-executed corpus structure.
    """
    structure = _build_source_type_map_as_executed(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Documents are at: {sources_dir}/
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array listing which fields hold text content — check this before reading field values.

{structure}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk, tr, sed
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you discover it; IDs are validated immediately against the corpus

## How to finish
When you have enough information, **output your final answer as plain text** — that ends the session. Do not call any tool for the final answer.

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Notes
- Use `select_doc_by_dsid` to register each relevant document as you find it — do not wait until the end.
- Questions vary: single-document, multi-document, conflicting sources, or unanswerable. If unanswerable, say so in plain text with no documents selected.
- Terminology mismatch is common — try synonyms and broader terms when exact searches return nothing.
"""


def build_v7_prompt(sources_dir: str) -> str:
    """v7: cwd=SOURCES_DIR (relative paths), high-result counter, no | head, --glob fix."""
    structure = _build_source_type_map_relative(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Your working directory is the corpus root. All paths are relative.
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array listing which fields hold text content — check this before reading field values.

{structure}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid as you discover it; IDs are validated immediately against the corpus

## How to finish
When you have enough information, **output your final answer as plain text** — that ends the session. Do not call any tool for the final answer.

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Search guidance
- Use relative paths: `rg "keyword" jira/` not `rg "keyword" generated_data/sources/jira/`
- Use `--glob` not `--include` with rg: `rg "keyword" . --glob="*.json"`
- Do NOT use `| head` on search results — the system handles large output and will show navigation hints
- Use `select_doc_by_dsid` to register each relevant document as you find it — do not wait until the end
- Questions vary: single-document, multi-document, conflicting sources, or unanswerable
- Terminology mismatch is common — try synonyms and narrower terms when broad searches return too many results
"""


def build_v7plus_prompt(sources_dir: str) -> str:
    """v7plus: v7 + stronger select_doc_by_dsid enforcement + concrete per-subdir flood hint."""
    structure = _build_source_type_map_relative(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Your working directory is the corpus root. All paths are relative.
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).
Each document also has a `content_field_names` array listing which fields hold text content — check this before reading field values.

{structure}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, head, find, xargs, jq, wc, tail, sort, uniq, cut, awk
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid

## Document selection — critical rule
**Every time you read a document that is relevant to the question, immediately call `select_doc_by_dsid(add=<dsid>)` before moving on.**
Do not wait until the end. Do not batch selections. Call it right after reading each relevant file.
The final answer is only as useful as the documents you have registered — if you skip this step, your retrieval result is lost.

## How to finish
When you have enough information, **output your final answer as plain text** — that ends the session. Do not call any tool for the final answer.

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Search guidance
- Use relative paths: `rg "keyword" jira/` not `rg "keyword" generated_data/sources/jira/`
- Use `--glob` not `--include` with rg: `rg "keyword" . --glob="*.json"`
- Do NOT use `| head` on search results — the system handles large output and will show navigation hints
- Questions vary: single-document, multi-document, conflicting sources, or unanswerable
- Terminology mismatch is common — try synonyms and narrower terms when broad searches return too many results
"""


def build_v9_prompt(sources_dir: str) -> str:
    """v9: v7plus + read tool for clean document content extraction with UUID."""
    structure = _build_source_type_map_relative(sources_dir)

    return f"""You are a research agent answering questions by searching a document corpus on disk.

## Corpus
Your working directory is the corpus root. All paths are relative.
Each document is a JSON file with a `dataset_doc_uuid` field (unique ID, format: dsid_XXXX).

{structure}

## Tools
- `run(command=...)` — execute shell commands: rg, grep, ls, tree, cat, find, xargs, jq, wc, tail, sort, uniq, cut, awk
- `read(path=...)` — read a document in clean format: returns the document title, content, and UUID. Prefer this over `cat` for reading individual documents.
- `select_doc_by_dsid(add=...)` — record a relevant document by its dataset_doc_uuid

## Workflow
1. Use `run` to search for relevant documents (rg, ls, find).
2. Use `read(path=...)` to read promising files — it returns clean title+content and the UUID at the end.
3. **Immediately call `select_doc_by_dsid(add=<dsid>)` after reading each relevant document.** Do not wait. Do not batch. The UUID is shown at the bottom of every `read` output.
4. Output your final answer as plain text when done — that ends the session.

## Session budget
You have {QUESTION_TIMEOUT_SECONDS} seconds per question. The tool footer shows `session: Xs` so you can pace yourself.

## Search guidance
- Use relative paths: `rg "keyword" jira/` not `rg "keyword" generated_data/sources/jira/`
- Use `--glob` not `--include` with rg: `rg "keyword" . --glob="*.json"`
- Do NOT use `| head` on search results — the system handles large output and will show navigation hints
- Questions vary: single-document, multi-document, conflicting sources, or unanswerable
- Terminology mismatch is common — try synonyms and narrower terms when broad searches return too many results
"""


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
    elif variant == "v4":
        return build_v4_prompt(sources_dir)
    elif variant == "v4plus":
        return build_v4plus_prompt(sources_dir)
    elif variant == "v5":
        # v5 uses the same prompt as v4plus; it differs only at the tool layer:
        # select_doc_by_dsid + force_finish_llm + expanded shell commands.
        return build_v4plus_prompt(sources_dir)
    elif variant == "v6":
        return build_v6_prompt(sources_dir)
    elif variant == "v7":
        return build_v7_prompt(sources_dir)
    elif variant in ("v7plus", "v8"):
        return build_v7plus_prompt(sources_dir)
    elif variant == "v9":
        return build_v9_prompt(sources_dir)
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
            f"[error] empty command — available: {_ALLOWED_CMDS_STR}",
            1,
            elapsed,
        )

    error = _validate_first_command(segments[0].command)
    if error:
        elapsed = (time.monotonic() - t0) * 1000
        return (error, 1, elapsed)

    # Progressive --help discovery (Technique 1): intercept bare/partial commands
    # before hitting the shell so the agent gets corpus-specific guidance instantly.
    # Only applies to the first segment — downstream pipe segments get shell behavior.
    help_hint = _progressive_help(segments[0].command)
    if help_hint:
        elapsed = (time.monotonic() - t0) * 1000
        return (help_hint, 1, elapsed)

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
                "Scope to a subdirectory or use a more specific pattern.",
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


def _extract_cat_path(command: str) -> str | None:
    """Extract the source file path from a cat command (first segment only)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens or os.path.basename(tokens[0]) != "cat":
        return None
    # Find first non-flag, non-operator token after 'cat' — that's the file path
    _SHELL_OPERATORS = {"|", "||", "&&", ";"}
    for t in tokens[1:]:
        if not t.startswith("-") and t not in _SHELL_OPERATORS:
            return os.path.normpath(t)
    return None


def make_run_tool_executor(
    cwd: str | None = None,
    session_start: float | None = None,
) -> Any:
    """Create a run tool executor with per-session state.

    Tracks per-session state for Technique 2 & 3 signals:
    - cmd index + session elapsed  → footer cost awareness
    - exact command history        → repeat annotation
    - zero-result counts per path  → subdirectory map hint after 5 misses
    - file read counts             → overflow tmp-file reminder on re-reads
    """
    _t0 = session_start if session_start is not None else time.monotonic()
    _cmd_index = [0]
    _seen: dict[str, int] = {}  # command → first cmd index
    _zero_counts: dict[str, int] = {}  # normalised base path → consecutive zeros
    _global_zero_count = [0]  # consecutive zeros across ALL paths
    _file_reads: dict[str, int] = {}  # normalised file path → read count
    _file_overflow: dict[str, str] = {}  # normalised file path → overflow tmp path
    _is_relative = cwd is not None and os.path.normpath(cwd) == os.path.normpath(
        os.path.abspath(SOURCES_DIR)
    )
    _subdirs_hint = _build_subdirs_hint(SOURCES_DIR, relative=_is_relative)

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

        # File re-read tracker (Technique 2): detect cat on a previously-read file.
        # When the same file is read again (different jq filter = different command,
        # so exact-repeat won't catch it), remind the agent it already has this content
        # and point it to the overflow tmp file if one exists for that source.
        file_reread_hint = ""
        cat_path = _extract_cat_path(command)
        if cat_path is not None:
            _file_reads[cat_path] = _file_reads.get(cat_path, 0) + 1
            read_count = _file_reads[cat_path]
            if read_count == 2:
                tmp_hint = ""
                if cat_path in _file_overflow:
                    tmp_hint = f" Full content already at {_file_overflow[cat_path]} — use grep/sed on that instead."
                file_reread_hint = f"[note: reading {os.path.basename(cat_path)} for the 2nd time.{tmp_hint}]"
            elif read_count >= 3:
                tmp_hint = ""
                if cat_path in _file_overflow:
                    tmp_hint = f" Use grep/sed on {_file_overflow[cat_path]} to search within it."
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(
                    read_count % 10 if read_count % 100 not in (11, 12, 13) else 0, "th"
                )
                file_reread_hint = (
                    f"[note: reading {os.path.basename(cat_path)} for the {read_count}{suffix} time — "
                    f"if the answer isn't here, it may not be in this file."
                    f"{tmp_hint}]"
                )

        # Detect rg --include= (grep flag, not valid for rg) and return actionable error.
        # Check only the first segment so pipe targets (e.g. grep --include=) aren't affected.
        first_seg = command.split("|")[0].split("&&")[0].split(";")[0]
        if re.search(r"\brg\b", first_seg) and "--include=" in first_seg:
            fixed = command.replace("--include=", "--glob=")
            return (
                f"[error] rg uses --glob not --include.\n"
                f"Try: {fixed}\n"
                f"[exit:2 | 0ms | cmd #{idx} | session: {session_elapsed:.0f}s]"
            )

        output, rc, elapsed_ms = execute_chain(command, cwd=cwd)

        # Detect | head -N on search commands: Layer 1 already truncated the output,
        # so Layer 2 overflow/hint mechanisms are silently dead. Emit a corrective note
        # so the agent knows to re-run without head (same pattern as --include fix above).
        head_match = re.search(r"\|\s*head\s+(?:-n\s+)?(\d+)", command)
        if head_match and re.search(r"^\s*(rg|grep)\b", command):
            n = head_match.group(1)
            output = (
                output
                + f"\n[note: | head limited output to {n} lines — results may be incomplete. "
                f"Remove | head; the system handles large output automatically "
                f"and saves full results to a navigable file.]"
            )

        # Record overflow tmp path for this file so future re-read hints can cite it.
        if cat_path is not None:
            m = re.search(r"Full output saved: (\S+)", output)
            if m:
                _file_overflow[cat_path] = m.group(1)

        # Per-path zero-result counter — emit subdirectory map hint at threshold
        zero_hint = _update_and_get_zero_hint(
            _zero_counts, command, output, rc, _subdirs_hint
        )

        # Global zero-result counter — fires when the agent can't find anything
        # across any path, signalling it's time to conclude or change strategy.
        base = _extract_search_base_path(command)
        if base is not None:
            if output.strip() == "" and rc == 1:
                _global_zero_count[0] += 1
            else:
                _global_zero_count[0] = 0

        global_zero_hint = ""
        gz = _global_zero_count[0]
        if gz == _GLOBAL_ZERO_WARN:
            global_zero_hint = (
                f"[note: {gz} consecutive searches returned no results across the corpus — "
                "the answer may use different terminology. "
                "Try broader or synonym terms, or call finish() if not found.]"
            )
        elif gz == _GLOBAL_ZERO_STRONG:
            global_zero_hint = (
                f"[note: {gz} consecutive searches returned no results — "
                "this information is likely not in the corpus. "
                "Call finish() with your best answer or 'not found'.]"
            )

        high_result_hint = _get_high_result_hint(
            command,
            output,
            rc,
            _subdirs_hint,
            sources_dir=cwd if _is_relative else None,
        )
        output = _apply_presentation_layer(output, command=command, cwd=cwd)

        # Technique 3: consistent footer with cmd index + session elapsed
        footer = f"[exit:{rc} | {elapsed_ms:.0f}ms | cmd #{idx} | session: {session_elapsed:.0f}s]"

        parts: list[str] = []
        if repeat_prefix:
            parts.append(repeat_prefix)
        parts.append(output)
        if file_reread_hint:
            parts.append(file_reread_hint)
        if zero_hint:
            parts.append(zero_hint)
        if high_result_hint:
            parts.append(high_result_hint)
        if global_zero_hint:
            parts.append(global_zero_hint)
        parts.append(footer)
        return "\n".join(parts)

    return _run


def make_select_doc_executor(
    uuid_index: dict[str, str],
    selected_ids: set[str],
) -> Any:
    """Create an executor for the select_doc_by_dsid tool.

    Validates document IDs against the UUID index at call time — invalid IDs
    are rejected immediately rather than silently accumulated and hallucinated.
    """

    def _select_doc(add: str | None = None, remove: str | None = None) -> str:
        if add:
            if add not in uuid_index:
                return (
                    f"[error] '{add}' not found in corpus — "
                    "check the dataset_doc_uuid value in the JSON file."
                )
            selected_ids.add(add)
            return "Document added."
        if remove:
            selected_ids.discard(remove)
            return "Document removed."
        return "[error] provide 'add' or 'remove' parameter."

    return _select_doc


def make_finish_tool_executor(selected_ids: set[str]) -> Any:
    def _finish(answer: str) -> str:
        raise FinishSignal(answer=answer, document_ids=sorted(selected_ids))

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
    uuid_index: dict[str, str],
    quiet: bool,
    cwd: str | None = None,
    read_tool: DocumentReadTool | None = None,
) -> dict[str, Any]:
    """Run the agentic loop for a single question.

    Returns a dict with keys:
        question_id, answer, document_ids,
        elapsed_seconds, iterations, commands_run, timed_out, llm_retries
    """
    start_time = time.monotonic()
    deadline = start_time + QUESTION_TIMEOUT_SECONDS

    selected_ids: set[str] = set()
    run_executor = make_run_tool_executor(cwd=cwd, session_start=start_time)
    select_doc_executor = make_select_doc_executor(uuid_index, selected_ids)
    finish_executor = make_finish_tool_executor(selected_ids)

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
    last_text_response = ""

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
                    elif tool_call.name == READ_TOOL:
                        if read_tool is not None:
                            path = tool_call.args.get("path", "")
                            raw = read_tool.execute(path)
                            # Apply overflow detection only — skip run-specific hints
                            result = _apply_presentation_layer(raw, command="", cwd=cwd)
                        else:
                            result = "[error] read tool not available in this variant."
                    elif tool_call.name == "select_doc_by_dsid":
                        result = select_doc_executor(**tool_call.args)
                    elif tool_call.name == "finish":
                        finish_executor(**tool_call.args)
                        result = "Done."
                    else:
                        result = (
                            f"[error] unknown tool '{tool_call.name}'. "
                            "Available tools: run, select_doc_by_dsid, finish."
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

        # No tool calls — LLM output plain text (natural end for v6, fallback for others)
        if full_response:
            last_text_response = full_response
            messages.append(Message(role="assistant", content=full_response))
        break

    # Time limit (or no-tool break) reached without finish()
    timed_out = time.monotonic() >= deadline
    elapsed = time.monotonic() - start_time

    if timed_out:
        if not quiet:
            print(
                f"\n[warn] time limit ({QUESTION_TIMEOUT_SECONDS}s) reached "
                f"after {iteration} iteration(s) for {question_id} "
                f"(elapsed: {elapsed:.1f}s)"
            )
        # Force finish: inject the warning then call a tools-disabled LLM to
        # extract a text answer from whatever the agent has gathered so far.
        messages = _prune_messages(
            messages + [Message(role="user", content=OUT_OF_TIME_USER_MESSAGE)]
        )
        force_llm = get_llm(tools=None, quiet=True, reasoning_level=None)
        try:
            forced_answer = ""
            for chunk in force_llm.generate(messages):
                if isinstance(chunk, str):
                    forced_answer += chunk
            if forced_answer:
                if not quiet:
                    print(f"  [forced finish] {forced_answer[:100]}...")
                return _make_result(forced_answer, sorted(selected_ids), timed_out=True)
        except Exception as exc:
            if not quiet:
                print(f"\n[warn] forced finish LLM call failed: {exc}")
    else:
        if last_text_response:
            if not quiet:
                print(f"\n[text finish] {question_id}: {last_text_response[:100]}...")
            return _make_result(
                last_text_response, sorted(selected_ids), timed_out=False
            )
        if not quiet:
            print(f"\n[warn] agent stopped without finish() for {question_id}")

    return _make_result("", sorted(selected_ids), timed_out=timed_out)


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
    parser.add_argument(
        "--questions",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a JSONL questions file (default: generated_data/questions.jsonl)",
    )
    args = parser.parse_args()

    use_quiet = args.parallelism > 1

    output_path = (
        args.output or f"answer_evaluation/answers_variant_{args.variant}.jsonl"
    )

    # Load UUID index for document ID validation by select_doc_by_dsid tool
    print("Loading UUID index...")
    uuid_index = load_or_build_uuid_index()
    print(f"  Indexed {len(uuid_index)} documents")

    # Build system prompt once (discovers source types from disk)
    system_prompt = build_system_prompt(SOURCES_DIR, args.variant)

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    questions_path = args.questions if args.questions else QUESTIONS_PATH

    # Determine which question IDs to run
    subset_ids: set[str] | None = None
    if args.subset_per_type is not None:
        subset_ids = load_subset_ids(questions_path, args.subset_per_type)
        if not use_quiet:
            print(
                f"Subset: {len(subset_ids)} questions ({args.subset_per_type} per type)"
            )

    questions = load_questions_jsonl(
        questions_path, limit=args.limit, question_ids=subset_ids
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
        agent_cwd = (
            os.path.abspath(SOURCES_DIR)
            if args.variant in _RELATIVE_CWD_VARIANTS
            else None
        )

        # v9: instantiate a fresh DocumentReadTool per question (stateful read tracking)
        read_tool: DocumentReadTool | None = None
        if args.variant == "v9" and agent_cwd is not None:
            read_tool = DocumentReadTool(
                base_dir=agent_cwd,
                generated_doc_contents=True,
                include_dsid=True,
            )
            tool_schemas = V6_TOOLS + [read_tool.get_schema(include_display_name=False)]
        elif args.variant in _V6_TOOL_VARIANTS:
            tool_schemas = V6_TOOLS
        else:
            tool_schemas = TOOLS

        llm = get_llm(tools=tool_schemas, quiet=use_quiet, reasoning_level=None)
        result = run_agent_for_question(
            question_id=q["question_id"],
            question=q["question"],
            llm=llm,
            system_prompt=system_prompt,
            uuid_index=uuid_index,
            quiet=use_quiet,
            cwd=agent_cwd,
            read_tool=read_tool,
        )
        append_result(output_path, result, write_lock)
        return result

    if args.parallelism == 1:
        for q in questions:
            process_one(q)
    else:
        future_timeout = QUESTION_TIMEOUT_SECONDS + 60
        future_start: dict[Any, float] = {}
        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {}
            for q in questions:
                f = executor.submit(process_one, q)
                futures[f] = q
                future_start[f] = time.monotonic()
            with tqdm(total=total, desc=f"[{args.variant}] Answering") as pbar:
                for future in as_completed(futures):
                    try:
                        future.result(timeout=future_timeout)
                    except Exception as exc:
                        q = futures[future]
                        elapsed = round(time.monotonic() - future_start[future], 2)
                        print(
                            f"\n[error] {q['question_id']} failed: {exc}\n"
                            + traceback.format_exc(),
                            flush=True,
                        )
                        append_result(
                            output_path,
                            {
                                "question_id": q["question_id"],
                                "answer": "",
                                "document_ids": [],
                                "elapsed_seconds": elapsed,
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
