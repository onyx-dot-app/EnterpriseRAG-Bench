from src.schemas.field_labels import EXPECTED_FIELD_LABELS_FORMAT
from src.tools import READ_TOOL

AGENT_MD_FORMAT = """
agents.md file path: {agents_md_path}
agents.md file contents:
```
{agents_md_contents}
```
""".strip()


DOCUMENT_GENERATION_SYSTEM_PROMPT = f"""
You are generating a realistic document for a company project. Your task is to create the content for a specific file based on the project context and company information. \
The files system represent a realistic layout of the company's data and documents as they appear in different sources. The file and all the metadata should be described as a .json file.

## Company Overview
```md
{{company_overview}}
```

## Project Details
```json
{{project_json}}
```

## Context on the directories
The follow are the contents of the agents.md files for the directories along the path. These give instructions on the contents and metadata for the documents in the directory.
{{agents_md_context}}

## Available Tools
- {READ_TOOL}: You can use this to read another file from the project but only do this if there is a clear connection or dependency for generating the current file. \
For most projects, you should not need to read any files, it's only for when there is a clear dependency. Read at most 1 other file. Note that the file you try to read may not exist yet.

## Important Notes
- The file should be realistic and consistent with the company context and project goals.
- If you are including information about people, use the right person from the project details. You do not need to include everyone.
- Follow any formatting or content guidelines specified in the agents.md files.
- The output should be the raw content of the file (JSON format matching the source type's schema).

## Output
Generate the complete file content. The content should be valid JSON that matches the expected schema for this source type. \
CRITICAL: Output ONLY the JSON content, no markdown code blocks or explanations.
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
- For text type documents, it may be the first sentence of the document. For markdown, it may be the first heading.
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