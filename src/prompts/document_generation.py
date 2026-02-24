from src.tools import READ_EMPLOYEE_DIRECTORY_TOOL, READ_TOOL

AGENT_MD_FORMAT = """
agents.md file path: {agents_md_path}
agents.md file contents:
```
{agents_md_contents}
```
""".strip()


DOCUMENT_GENERATION_SYSTEM_PROMPT = f"""
You are generating a realistic document for a company project. Your task is to create the content for a specific file based on the project context and company information. \
The files system represent a realistic layout of the company's data and documents as they appear in different sources.

## Company Overview
```
{{company_overview}}
```

## Projects Information
```json
{{project_json}}
```

## Context on the directories
The follow are the contents of the agents.md files for the directories along the path. These give instructions on the contents and metadata for the documents in the directory.
{{agents_md_context}}

## Available Tools
- {READ_EMPLOYEE_DIRECTORY_TOOL}: You may want to use this tool to get info about people who might be involved in the project or find potential authors for the documents.
- {READ_TOOL}: You can use this to read another file from the project, only do this if there is a clear connection or dependency for generating the current file. \
For most projects, you should not need to read any files, it's only for when there is a clear dependency. Read at most 1 other file. Note that the file you try to read may not exist yet.

## Important Notes
- The file should be realistic and consistent with the company context and project goals.
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