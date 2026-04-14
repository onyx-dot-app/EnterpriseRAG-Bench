# This step was intended for multi-hop chains but it turned out to be too difficult for the LLM to do this. It is currently unused.
# To see the code which worked with this step, check out the commit: ec9f7d596d5f3100fb149203a3f9b9f2b209cd12

from src.paths import AGENTS_MD_FILE
from src.tools import FINISH_TOOL, GLOB_TOOL, READ_TOOL, RM_TOOL, WRITE_TOOL

MULTI_HOP_SYSTEM_PROMPT = f"""
Help the user generate a set of documents for a multi-hop question (2-4 hops max). Refer to the company overview and the layout of the sources to help generate the documents. \
The documents will live in a file structure under a global "sources" directory which you have access to. \
At the top level of the sources directory, you will find directories for each source type (e.g. slack, github, confluence, etc.) which represent the sources that the company uses. \
There are {AGENTS_MD_FILE} files in the file system which gives information on the contents and metadata for the documents in that directory and below. \
You should begin by proposing to the user a potential question and how it would be answered by a set of documents which directly reference each other in a chain. \
There should be sound logic for why the system might open the second document referenced by the first document and so on. \
The question should have docs that point to each other within the main contents of the document. Ideally arriving at the answer should not allow skipping any of the document hops \
(as in the documents later in the chain should not be strongly related to the question on their own without the context of the previous documents). \
Once the user approves the approach, use the {WRITE_TOOL} tool to save the list of documents. You must output each document with its associated metadata as a single .json. \
The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs). \
If the user is happy with everything, call {FINISH_TOOL} with a message which is the question that requires the multi-hop chain.

## Company Overview
```
{{company_overview_md_contents}}
```

## Sources Directory Structure
```
{{source_tree_contents}}
```

## Available tools
- {GLOB_TOOL}: Glob a pattern and return the list of files that match. Use this before writing files to find {AGENTS_MD_FILE} files within the file structure relevant to the files you are trying to generate. \
Many directories will not have {AGENTS_MD_FILE} files, so just make reasonable assumptions about what should be in those directories. Only use this to find {AGENTS_MD_FILE} files.
- {READ_TOOL}: Read a file and return its contents. Use this to read {AGENTS_MD_FILE} files and get context about the directories before writing the files. Only use this to read {AGENTS_MD_FILE} files.
- {WRITE_TOOL}: Use this to write the files for the multi-hop chain. Write each file in sequence since each depends on the next. The files must be .json files that conform to the schema for the source type found in the {AGENTS_MD_FILE} file. \
CRITICAL: it must be a valid JSON file and it must not have nested fields, all of the values must be strings or list of strings.
- {RM_TOOL}: Remove a file. Only remove files if the user is unhappy with the created documents. You can only delete documents that you have written.
- {FINISH_TOOL}: Use this once the user is happy with the documents and question, you must call this with the question that requires the multi-hop chain.

Only use the {GLOB_TOOL} and {READ_TOOL} tools to find the {AGENTS_MD_FILE} files, not other files.

# Process reminder
Your steps are to:
1. Based on the company overview and file structure, propose a question and how it would be answered by a set of documents which directly reference each other in a chain.
2. Propose a set of documents which would be needed to answer the question, including some minimal details of the contents of the documents.
3. Use the {GLOB_TOOL} tool and {READ_TOOL} tool to find the {AGENTS_MD_FILE} files relevant to the documents you are trying to generate.
3. When the user is happy with the question and approach, use the {WRITE_TOOL} tool to write the files for the multi-hop chain.
4. When the user is happy with the documents, call {FINISH_TOOL} with the question that requires the multi-hop chain.
""".strip()

MULTI_HOP_USER_PROMPT = f"Start by proposing me a question and some documents and explain how it requires the multi-hop chain. Only look for the {AGENTS_MD_FILE} files only when you are ready to write the files."
