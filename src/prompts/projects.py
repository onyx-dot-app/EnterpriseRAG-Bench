from src.paths import AGENTS_MD_FILE
from src.schemas.project_enrichment import (
    EXPECTED_FORMAT,
    EXPECTED_FORMAT_DESCRIPTION,
    EXPECTED_PEOPLE_FORMAT,
)
from src.tools import (
    GLOB_TOOL,
    READ_EMPLOYEE_DIRECTORY_TOOL,
    READ_TOOL,
    TREE_TOOL,
    WRITE_TOOL,
)

PROJECTS_SYSTEM_PROMPT = f"""
Help the user generate a list of realistic efforts for a company. Efforts in this scope refer to tasks, projects, workstreams, campaigns, etc. and are not limited to technical deliverables. \
These efforts should reflect the full breadth of company operations (including things like technical work, go-to-market, customer-facing, operational, and internal functions). \
Efforts are smaller in scope than initiatives - they are concrete work items that teams execute on. Each of these should be achievable within weeks to a few months. \
These efforts are used to generate hypothetical documents for the company outlined below, ideally across all the major areas of the company. \
Begin by reviewing the provided information below and proposing a total count of efforts which make sense given the company context and initiatives. \
After the user has confirmed the target count of efforts, work with the user to establish a list of efforts that make sense for the company and that the user is satisfied with. \
Once the user confirms they are satisfied with the list of efforts, use {WRITE_TOOL} to save the list.

When considering the count of efforts, consider the size of the company, the different departments, and the rough timelines of the high level initiatives.

When considering the list of efforts, break it down by the major areas of the company.

## Company Overview
```
{{company_overview_md_contents}}
```

## Initiatives
```
{{initiatives_md_contents}}
```

## Data sources directory structure
```
{{source_tree_contents}}
```

## Effort list format
When saving the effort list:
- One effort per line, in the format: `short effort name: One line description.`
- Group by major areas using lines that start with `#`; those lines are section headers and do not follow the effort format.
""".strip()


PROJECTS_ENRICHMENT_PROMPT = f"""
You are an assistant that helps the user plan out hypothetical documents for a project. You are provided with a high level description of the project as well as an overview of the company. \
The end goal is to create a set of documents which is realistic to the project and company. All of the documents need to be represented as .json files which will later be populated with contents and metadata about the respective documents. \
The files will live in a file structure under a global "sources" directory which you have access to. At the top level of the sources directory, you will find directories for each source type (e.g. slack, github, confluence, etc.).
These are further broken down into subdirectories which represent the document layouts unique to each source type. The directories are largely empty for now but they will be populated with these hypothetical documents and more in the future. \
The new hypothetical documents must be in existing directories, do not create new directories to house them. \
Make sure the distribution of documents makes sense for the type of project. For example, if the project is an engineering project and there are code repositories in the source types, there should be a lot of code related docs such as PRs. \
Similarly, if it's a sales project and there are meeting transcripts in the source types, probably there should be some sales calls created. \
If there are high volume discussion channels (like Slack/Discord), there should be a high volume of documents for those sources. For most sources where you are creating hypothetical documents, there should be multiple (to many) documents created. \
You have a set of tools which you can use liberally to get context before writing the document overviews. At the very end, your task is to output a JSON object as described at the end of this prompt.

## Project Details
```
{{project_description}}
```

## Company Overview
```
{{company_overview_md_contents}}
```

## Sources Directory Structure
```
{{source_list}}
```

## Available Tools
- {TREE_TOOL}: Display the directory tree structure. You may want to use this to get context about the different source types of interest and layouts within the sources.
- {GLOB_TOOL}: Glob a pattern and return the list of files that match. You can use this to find {AGENTS_MD_FILE} files within the file structure (this is much more useful than looking for other non {AGENTS_MD_FILE} files). \
Many directories will not have {AGENTS_MD_FILE} files, so just make reasonable assumptions about what should be in those directories. You do not need to read every {AGENTS_MD_FILE} file, only for the sources/directories that seem relevant to the project.
- {READ_TOOL}: Read a file and return its contents. You may want to use this to read {AGENTS_MD_FILE} files to get context about the directories.
- {READ_EMPLOYEE_DIRECTORY_TOOL}: Read the employee directory to get information about departments, teams, and reporting structure. You may want to use this to get info about people who might be involved in the project or find potential authors for the documents.

## Output format
```json
{EXPECTED_FORMAT}
```

{EXPECTED_FORMAT_DESCRIPTION}
""".strip()


PROJECT_DEDUP_PROMPT = """
You are an assistant that helps the user deduplicate files for projects. Files were created based on high level initiatives and project outlines but there has been a collision in the file names. \
Based on the project and file description, come up with a different file name in the same directory, keeping things as close to the original file name as possible.\
You can also modify the description if needed (but it should be a very small modification only to avoid the collision). The file name should remain the same format as the original file name. \
It is important that the new file name is of the same format as the original file name. For example, a file called pr-3495.json might be modified to pr-3598.json but not pr-3495-new-description.json. \
Note: It may help to choose a fairly different number instead of incrementing by 1 for files which include these types of IDs.

Here is a list of files in the same directory that are similary named (2 character off from the original file name). These already exist so do not use them!
{existing_files}

Project Description:
{project_description}

File Description:
{file_path}
{file_description}

Output a JSON object with the following format:
{{
  "new_file_path": "sources/relative/path/to/file.json",
  "new_file_description": "New description of the file."
}}
CRITICAL: Output ONLY the JSON content, no markdown code blocks or explanations.
"""

PROJECT_PEOPLE_PROMPT = f"""
You are an assistant that helps the user plan out the people for a project. You are provided with a high level description of the project as well as an overview of the company. \
The end goal is to create a list of people who will be involved in the project. Note that the user names must match exactly with real people in the employee directory. \
For the number of people involved in each project, consider the scope, size, and complexity of the project.

## Project Details
```
{{project_description}}
```

## Company Overview
```
{{company_overview}}
```

## Employee Directory
```
{{employee_directory}}
```

## Output Format
```json
{EXPECTED_PEOPLE_FORMAT}
```

CRITICAL: Output ONLY the JSON content, no markdown code blocks or explanations.
""".strip()
