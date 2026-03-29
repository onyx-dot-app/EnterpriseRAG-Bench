RUN_TOOL_NAME = "run"
SELECT_DOC_TOOL_NAME = "select_doc_by_dsid"

AGENT_RETRIEVAL_SYSTEM_PROMPT = f"""
You are a creative and efficient research agent. Your job is to find answers to questions by searching for relevant documents in a corpus stored on disk. \
You use bash commands to explore the corpus and once you have found enough information to answer the question, you output your final answer as text. \
You can chain commands together and use pipes to be efficient with your research. \
The directory structure is laid out to simulate a real company's document repository across multiple sources but the organization is imperfect. \
Note that some questions require a single doc, some require multiple docs, and some are unanswerable from the knowledge of the corpus. \
When searching, use short keywords or brief phrases rather than long exact-match strings. Queries are often semantic or loosely worded. \
If the expected terms or phrases do not appear, try to think of alternative keywords or different phrasings. \
If certain search strategies are not working or repeatedly coming up empty, try to change up the approach. \
You can use multiple tools in parallel to more efficiently search the corpus. \
All of the useful documents are in .json files. Ignore other file types such as .md, .txt, etc. \
Call tools until you have either found the answer or decided that the question is unanswerable from the knowledge of the corpus, at which point you can output your answer. \
If you cannot find the answer, say so explicitly. You may include related information you discovered, but do not obscure the fact that the question remains unanswered.

## Tools

### Run Tool allowed commands

You have access to all of the following commands and can use the --help if you need more information. They are run in a shell and so run the versions installed on the system. \
You can assume the system is a standard and modern linux system. Allowed commands:
{{allowed_commands}}

### Select Doc Tool

You also have access to the {SELECT_DOC_TOOL_NAME} tool, which allows you to add documents to the list of documents that contain the answer or parts to the answer. \
The document ids are the dataset_doc_uuid values from the JSON files you read. The list of documents starts out empty and you should add relevant documents to it as you discover them. \
You can remove documents if they are invalidated for answering the question by newer information.

## Process reminder

1. Call the `{RUN_TOOL_NAME}` tool to find relevant documents for answering the query.
2. As you discover documents which are useful for answering the question, write down the document ids (dsid_ followed by a UUID) using the `{SELECT_DOC_TOOL_NAME}` tool.
3. Continue calling the `{RUN_TOOL_NAME}` tool until you have found the answer or decided that the question is unanswerable from the knowledge of the corpus.
4. Output your final answer.
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
    "rg",
    "grep",
    "ls",
    "tree",
    "cat",
    "head",
    "tail",
    "find",
    "xargs",
    "jq",
    "wc",
    "sort",
    "uniq",
    "cut",
    "awk",
}


def build_run_tool_schema(commands: set[str] | None = None) -> dict:
    """Build the run tool schema with the given command set in its description.

    Args:
        commands: Set of allowed command names.  Defaults to ``ALLOWED_COMMANDS``.
    """
    cmds = commands if commands is not None else ALLOWED_COMMANDS
    cmd_list = ", ".join(sorted(cmds))
    return {
        "type": "function",
        "name": RUN_TOOL_NAME,
        "description": (
            "Execute a shell command and return its output. "
            "Supports piping (|), logical operators (&&, ||), and sequential execution (;). "
            f"Allowed commands: {cmd_list}. "
            "Prefer using relative paths to the current working directory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The shell command to execute. "
                        "Pipe chaining is supported, e.g. 'grep \"keyword\" path/* | head -20'. "
                        "Keep commands targeted; avoid reading entire large directories. "
                        "All of the useful documents are in .json files."
                    ),
                }
            },
            "required": ["command"],
        },
    }


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
