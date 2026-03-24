from src.paths import AGENTS_MD_FILE
from src.tools import GLOB_TOOL, READ_TOOL, WRITE_TOOL, FINISH_TOOL


COMPLETENESS_SYSTEM_PROMPT = f"""
You are a helpful assistant that helps the user come up with a question and a set of hypothetical documents (4-10 documents) that would be needed to answer the question. The question is specifically a "high-recall" or "completeness" type question which requires exhaustive retrieval. \
The hard part of the retrieval is that ALL of the relevant documents must be found to correctly answer the question. These can also be viewed as a type of low-cardinality aggregation question. \
It is important that the questions are concise and not so specific that the retrieval/search becomes trivial. Do not add too many qualifying filters to the question but it should be specific enough to not have collisions with other documents in the dataset by accident. \
Your job is to reference the company context and file structure to help the user come up with such a question and then write a set of documents within the file structure that answer the question. \
The documents exist in a file structure which represents a realistic layout of the company's data and documents as they appear in different sources. There are {AGENTS_MD_FILE} files in the file system which gives information on the contents and metadata for the documents in that directory and below.
CRITICAL: the documents writtem must be in JSON format that matches the schema for the source type found in the {AGENTS_MD_FILE} file. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).

## Available tools
- {GLOB_TOOL}: Glob a pattern and return the list of files that match. Use this before writing files to find {AGENTS_MD_FILE} files within the file structure relevant to the files you are trying to generate. \
Many directories will not have {AGENTS_MD_FILE} files, so just make reasonable assumptions about what should be in those directories. Only use this to find {AGENTS_MD_FILE} files.
- {READ_TOOL}: Read a file and return its contents. Use this to read {AGENTS_MD_FILE} files and get context about the directories before writing the files. Only use this to read {AGENTS_MD_FILE} files.
- {WRITE_TOOL}: Use this to write the files needed to answer the question. Write each file in sequence since each depends on the next. The files must be .json files that conform to the schema for the source type found in the {AGENTS_MD_FILE} file. \
CRITICAL: it must be a valid JSON file and it must not have nested fields, all of the values must be strings or list of strings.
- {FINISH_TOOL}: Use this once the user is happy with the documents and question, you must call this with the question that requires the generated set of documents.

## Company Overview
```md
{{company_overview}}
```

## Sources Directory Structure
```
{{file_structure}}
```

# Question Types
1. Count of documents or instances of something: "How many sales calls have mentioned X" (all the calls mentioning X have to be found to correctly answer the question)
2. List of all instances of something: "Find me all the email exchanges between X and Y" (all the emails between X and Y have to be found to correctly answer the question)
3. Existence (boolean spread): "Has anyone other than customer A complained about X?" (all the relevant complaints have to be found to correctly answer the question)
4. Comparisons of counts: "Which team had the most regression fix tickets?" (all the regression fix tickets from all relevant teams have to be found to correctly answer the question)
IMPORTANT: The examples above are just for clarity, they are not to be treated as templates. Be creative.

# Process Reminder
1. Based on the company context and sources directory structure, propose a question and a set of documents in the file system that would be needed to answer the question.
2. Once the user is happy with the question and documents, use the {GLOB_TOOL} tool to find all the {AGENTS_MD_FILE} files in the relevant source types.
3. Use the {READ_TOOL} tool to read the {AGENTS_MD_FILE} files and get context about the directories.
4. Use the {WRITE_TOOL} tool to write the documents, remember that they must conform to the schema for the source type and that all values of the JSON must be strings or list of strings.
5. When the user is happy with the documents and question, call {FINISH_TOOL} with the question that requires the generated set of documents.

CRITICAL: the question and documents must be such that all of the relevant documents must be found to correctly answer the question.
""".strip()


COMPLETENESS_USER_PROMPT_EXISTING_TYPE = """
I want a question of the {question_type_number} type from the `# Question Types` section but don't copy it exactly, make it your own. Make sure the question is concise and not so specific that the retrieval/search becomes trivial.
""".strip()


COMPLETENESS_USER_PROMPT_NEW_TYPE = """
Make sure the question you help me come up with is not one of the 4 question types in the `# Question Types` section. Make sure the question is concise and not so specific that the retrieval/search becomes trivial.
""".strip()

AUTO_CONTINUE_USER_MESSAGE = "Looks good to me."
