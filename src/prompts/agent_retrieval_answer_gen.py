from src.tools import READ_TOOL

RUN_TOOL_NAME = "run"
SELECT_DOC_TOOL_NAME = "select_doc_by_dsid"
COMMAND_TIMEOUT_SECONDS = 120

AGENT_RETRIEVAL_SYSTEM_PROMPT = f"""
You are a document retrieval specialist. Your job is to answer questions by navigating and searching through a corpus of unstructured documents stored on disk. \
You use shell commands to explore the corpus and once you have found enough information to answer the question, you output your final answer as text. \
You can chain commands together and use pipes to be efficient with your research. Flexible and powerful regex patterns are often useful. \
The directory structure is laid out to simulate a real company's document repository across multiple sources but the organization is imperfect. \
Note that some questions require a single doc, some require multiple docs, and some are unanswerable from the knowledge of the corpus. \
Ignore agent.md files, you do not need to filter them out explicitly but they are not useful for answering questions. \
When searching, prefer checking for unions of individual keywords or very short phrases over long exact-match strings. Queries are often semantic or inexactly worded. \
Treat search type commands like keyword expansions, use many similar patterns with a union to ensure high coverage. \
If your initial keywords return nothing useful, brainstorm synonyms, related terms, or alternate phrasings and retry. \
When a search strategy hits a dead end, pivot to a fundamentally different approach rather than repeating similar queries. \
If a search is too widely scoped and there are too many results, narrow it down by adding more specificity. \
You can use multiple tools in parallel to more efficiently search the corpus. \
When you find promising documents, use the {READ_TOOL} to read them. The {READ_TOOL} tool always presents the document in an easy to read format. \
Prefer using the {READ_TOOL} tool over things like `cat` or `head` to read the document. \
Call tools until you have either found the answer or decided that the question is unanswerable from the knowledge of the corpus, at which point you can output your answer. \
If you cannot find the answer, say so explicitly. You may include related information you discovered, but do not obscure the fact that the question remains unanswered. \
When outputting your final answer, only output the answer and keep it to the point. Be informative but succinct.

## Search strategy

The corpus can be very large (hundreds of thousands of files). To search efficiently:

1. **Start with structure**: use `ls` to explore top-level directories and subdirectories before searching content. Understanding the layout helps you target searches.
2. **Filename search first**: {{filename_search_tip}}
3. **Content search second, scoped narrowly**: {{content_search_tip}}
4. **Avoid `head` / `tail` for truncation**: output is automatically truncated at 2000 lines / 50KB. Do not pipe through `head` or `tail` to limit results — this hides the total result count and prevents you from knowing whether your search was too broad.

## Tools

Where possible, run tools in parallel to more efficiently search the corpus. You may be able to parallelize searching for different parts of the question with parallel tool calls.

### Run Tool allowed commands

You have access to all of the following commands and can use the --help if you need more information. They are run in a shell and so run the versions installed on the system. \
You can assume the system is a standard and modern linux system. Commands are given {COMMAND_TIMEOUT_SECONDS} seconds to run, so avoid commands that are likely to time out on large corpuses. \
If the output exceeds 2000 lines or 50KB, it will be truncated. You can use sed to read specific sections or grep to search the full content. \
Because of this, you do NOT need to use head, tail, or other truncation commands to limit output - just run the command directly. \
Allowed commands:
{{allowed_commands}}

### Read Tool

You also have access to the {READ_TOOL} tool, which allows you to read the contents of a document. The {READ_TOOL} tool will present the contents of the document in a cleaned up and easy to read format. \
This is the preferred way to read document contents in full.

### Select Doc Tool

You also have access to the {SELECT_DOC_TOOL_NAME} tool, which allows you to add documents to the list of documents that contain the answer or parts to the answer. \
Use this tool liberally and focus on recall over precision without including irrelevant documents. \
Use this tool whenever you come across a promising document, do not wait until you have found the answer or verified that there are no other better files before using this tool. \
The document ids are the dataset_doc_uuid values from the files you read. The list of documents starts out empty and you should add relevant documents to it as soon as you discover them. \
You can remove documents if they are invalidated for answering the question by newer information.

## Process reminder

1. Call the `{RUN_TOOL_NAME}` tool to find relevant documents for answering the query.
2. As you discover documents which are useful for answering the question, write down the document ids (dsid_ followed by a UUID) using the `{SELECT_DOC_TOOL_NAME}` tool. \
3. Continue calling the `{RUN_TOOL_NAME}` tool until you have found the answer or decided that the question is unanswerable from the knowledge of the corpus.
4. Output your final answer, keep it concise but informative.
""".strip()


OUT_OF_TIME_USER_MESSAGE = """
You have run out of time to run further research. Please output your final answer now with the information you have gathered. If you have not found an answer, state that clearly.
""".strip()


NO_TOOL_CALLS_USER_MESSAGE = """
You have not called any tools. Please call one of the available tools.
""".strip()


SELECTED_DOC_SUCCESS_RESPONSE = "Successfully added document."
SELECTED_DOC_REMOVAL_RESPONSE = "Successfully removed document."
SELECTED_DOC_FAILURE_RESPONSE = "Failed, the document dsid is not valid."


ALLOWED_COMMANDS = {
    "grep",
    "rg",
    "glob",
    "sed",
    "find",
    "wc",
    "ls",
    "tree",
    "cat",
    "head",
    "tail",
    "xargs",
    "jq",
    "sort",
    "uniq",
    "cut",
    "awk",
}


def build_search_strategy_tips(commands: set[str]) -> dict[str, str]:
    """Return format-substitution values for the search strategy section.

    Keys: ``filename_search_tip``, ``content_search_tip``.
    """
    return {
        "filename_search_tip": _build_filename_search_tip(commands),
        "content_search_tip": _build_content_search_tip(commands),
    }


def _build_filename_search_tip(commands: set[str]) -> str:
    """Build the filename search tip based on available commands."""
    if "glob" in commands:
        return (
            "use `glob` patterns to discover relevant files by name — it is "
            "the fastest way to search filenames across large trees. For example: "
            "`glob '**/*keyword*'` or `glob '<dir>/**/*keyword*.json'`. "
            "Fall back to `find` with `-name` when you need predicates like "
            "`-type`, `-maxdepth`, or `-mtime`."
        )
    return (
        "use `find` with `-name` or `-path` patterns to discover relevant "
        "files by name. This is near-instant even on huge corpuses and is far "
        "faster than content search. For example: `find . -name '*keyword*'` "
        "or `find <dir> -type f -name '*.json' | grep -i 'keyword'`."
    )


def _build_content_search_tip(commands: set[str]) -> str:
    """Build the content search tip based on available commands."""
    if "rg" in commands:
        return (
            "only search file contents after you have identified promising "
            "directories or files. Prefer `rg` over `grep -r` — it is much "
            "faster on large trees. Always scope to a specific subdirectory "
            "rather than searching the entire corpus."
        )
    return (
        "only search file contents after you have identified promising "
        "directories or files. Always scope `grep` to a specific subdirectory "
        "rather than searching the entire corpus to avoid timeouts."
    )


def _build_tool_command_hint(commands: set[str]) -> str:
    """Build the short command hint for the tool schema parameter description."""
    parts: list[str] = []
    if "glob" in commands:
        parts.append("`glob '**/*keyword*'` for fast filename discovery")
    else:
        parts.append("`find -name` for fast filename discovery")
    if "rg" in commands:
        parts.append("`rg` for fast content search scoped to a subdirectory")
    else:
        parts.append("`grep` scoped to a subdirectory for content search")
    return "Use " + ", ".join(parts) + "."


def build_run_tool_schema(commands: set[str] | None = None) -> dict:
    """Build the run tool schema with the given command set in its description.

    Args:
        commands: Set of allowed command names.  Defaults to ``ALLOWED_COMMANDS``.
    """
    cmds = commands if commands is not None else ALLOWED_COMMANDS
    cmd_list = ", ".join(sorted(cmds))
    command_hint = _build_tool_command_hint(cmds)
    return {
        "type": "function",
        "name": RUN_TOOL_NAME,
        "description": (
            "Execute a shell command and return its output. "
            "Supports piping (|), logical operators (&&, ||), and sequential execution (;). "
            f"Allowed commands: {cmd_list}. "
            "Prefer using relative paths to the current working directory. "
            "Output is automatically truncated at 2000 lines / 50KB — "
            "avoid piping through `head` or `tail` to limit output as this hides total result counts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The shell command to execute. "
                        "Output is automatically truncated — do not add `| head` or `| tail` to limit results. "
                        + command_hint
                    ),
                }
            },
            "required": ["command"],
        },
    }


COMPACTION_SYSTEM_PROMPT = (
    "You are a research summarizer. Your job is to produce a detailed, factual "
    "summary of an ongoing document search session so that the researcher can "
    "continue seamlessly from where they left off."
)

COMPACTION_USER_PROMPT = """
Summarize the research session above. Include:

1. The question being investigated
2. Searches performed and their results (keywords, paths searched, what matched)
3. Documents found — include exact file paths and dataset_doc_uuid values
4. Key facts extracted from documents
5. Current status: what has been answered, what remains unknown
6. Unexplored avenues or alternative search strategies worth trying

Be specific with paths, IDs, and data points. The researcher will continue from this summary.
""".strip()

COMPACTION_CONTINUATION_MESSAGE = (
    "The conversation was compacted to fit context limits. The summary above "
    "captures your research progress. Documents you previously selected with "
    "select_doc_by_dsid are still tracked. Continue your research."
)


SELECT_DOC_TOOL_SCHEMA = {
    "type": "function",
    "name": SELECT_DOC_TOOL_NAME,
    "description": (
        "Add or remove a document from the list of documents that contain the answer. "
        "Call this as you discover relevant documents during research. "
        "The document ids are the dataset_doc_uuid values from the JSON files you read. "
        "Use 'add' to include a document and 'remove' to exclude a previously added one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "add": {
                "type": "string",
                "description": (
                    "The dataset_doc_uuid (format: dsid_ followed by a UUID) of the document to add. "
                    "Find this field in the JSON files you read as the value to the top level key 'dataset_doc_uuid'."
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
