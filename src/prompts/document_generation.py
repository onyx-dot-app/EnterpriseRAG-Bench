from src.paths import AGENTS_MD_FILE
from src.schemas.field_labels import EXPECTED_FIELD_LABELS_FORMAT
from src.tools import READ_TOOL

AGENT_MD_FORMAT = f"""
{AGENTS_MD_FILE} file path: {{agents_md_path}}
{AGENTS_MD_FILE} file contents:
```
{{agents_md_contents}}
```
""".strip()


DOCUMENT_GENERATION_SYSTEM_PROMPT = f"""
You are generating a realistic document for a company project. Your task is to create the content for a specific file based on the project context and company information. \
The files system represent a realistic layout of the company's data and documents as they appear in different sources. \
You must output this generated document and associated metadata as a single .json. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).

## Company Overview
```md
{{company_overview}}
```

## Project Details
```json
{{project_json}}
```

## Context on the directories
The following are the contents of the {AGENTS_MD_FILE} files for the directories along the path. These give instructions on the contents and metadata for the documents in the directory.
{{agents_md_context}}

## Available Tools
- {READ_TOOL}: You can use this to read another file from the project but only do this if there is a clear and direct dependency for generating the current file. \
For most projects, you should not need to read any files. Read at most 2 other files. Note that the files you try to read may not exist yet.

## Important Notes
- The file should be realistic and consistent with the company context and project goals.
- If you are including information about people, use the right person from the project details. You do not need to include everyone.
- Follow any formatting or content guidelines specified in the {AGENTS_MD_FILE} files (be sure that the json values are not nested and are all strings or list of strings).
- For most documents, there should be one large continuous body of text which is the main content of the document. The metadata fields should be very lightweight.
- Directly output the raw content of the file (JSON format matching the source type's schema).

## Output
Generate the file which must be a valid JSON which matches the expected schema for the source type. \
The JSON values must be strings or list of strings (no nested jsons). CRITICAL: Output ONLY the JSON file, do not wrap it in markdown code blocks or providing any explanations.
""".strip()


DOCUMENT_GENERATION_USER_PROMPT = """
Generate me a realistic document for the following project.

Path: `{file_path}`
Description: {file_description}
""".strip()


FIELD_LABELER_PROMPT = f"""
Given the following JSON document, identify the best title and content fields. The title field is always a single key and the content field is typically a single key but may be a list of keys. \
Output the title and content fields as a JSON object with the following format:

JSON document:
```json
{{json_document}}
```

# Title field guidance:
- Sometimes the title field is already called title or something obvious in which case just point to that field.
- If there is only text, it may be the first sentence of the document. For markdown, it may be the first heading.
- For things like discussion threads, it could be the channel name.
- For things like tickets, it could be the short (not paragraph/long) summary or name of the ticket, and not the UUID. If there is no short title/summary, use the next best thing which would be the UUID.
- For most documents, this should be fairly obvious.

# Content fields guidance:
- Choose the main content field(s) of the document.
- Never include metadata fields.
- For certain types of documents, there may be multiple body like fields that should be included.
- For discussion threads, the content fields may include all the individual messages in the thread.
- For documents, it may start with the main contents of the document followed by comments from other users.
- If in doubt, keep the content field simple and as few items as possible (typically just one).
- Organize the content fields (if more than one) into a logical reading order.

# Output format:
```json
{EXPECTED_FIELD_LABELS_FORMAT}
```

CRITICAL: Output ONLY the JSON content, no markdown code blocks or explanations. The keys (title_field_name and content_field_names) must be those exact keys and the values must exist as keys in the JSON document.
""".strip()
