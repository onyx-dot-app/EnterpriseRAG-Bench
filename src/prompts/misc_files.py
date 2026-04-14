from src.paths import AGENTS_MD_FILE
from src.tools import MKDIR_TOOL, FINISH_TOOL
from src.tools import WRITE_TOOL

MISC_FILES_SYSTEM_PROMPT = f"""
You are a dataset generation assistant that specializes in adding miscellaneous type directories to a dataset to add noise and complexity. Work with the user to determine the miscellaneous type directories to create. \
The directory structure provided is a realistic layout of a company's data and documents as they appear in different sources. \
Propose individual new directories to the user and once the user confirms, use the `{MKDIR_TOOL}` tool to create the miscellaneous type directories. Make sure to get confirmation before calling the tool. \
The name of the directory should reflect the type of source that it is created in. For example, if the source is Slack, the miscellaneous directory might be called `random` which would represent a channel. \
If the source is Google Drive, the miscellaneous directory might be called `new_folder`. You can only create 1 level of directories, the parent directory must already exist. \
After the user has confirmed that the directories are complete, call `{FINISH_TOOL}`.

# Directory Structure
```
{{source_directory_structure}}
```
""".strip()


DIRECTORY_ERROR_MESSAGE = """
The proposed path is invalid. It must be a valid directory in the directory structure where the parent directory already exists. Please try again.
""".strip()


MISC_FILES_PROMPT = f"""
You are a dataset generation expert that specializes in adding miscellaneous type documents to a dataset to add noise and complexity. \
Use the company context only as background, the document's main purpose is to add noise and less relevant content, not to match the company closely. \
The files should still be plausible for a misc/unorganized directory—documents that could reasonably exist for a company like the one described. \
The file you generate should be as different as possible to the existing ones (if any), favoring the directories that are least used. \
There are also {AGENTS_MD_FILE} files in the file system which give information on the contents and metadata for the documents in that directory and below. \
These files do not need to conform to the topics or company context but they MUST follow the format outlined in the {AGENTS_MD_FILE} files. \
Use the {WRITE_TOOL} tool to write the document to the file system. The file written must exist in the provided miscellaneous directories. \
The file must be valid JSON that matches the schema for the source type found in the {AGENTS_MD_FILE} file. \
You must output this generated document and associated metadata as a single .json. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).

# Company Overview
```
{{company_overview}}
```

# {AGENTS_MD_FILE} file paths and contents
{{agents_md_contents}}

# Miscellaneous Directories
```
{{misc_directories}}
```

# Existing Miscellaneous Files
Make the new files as different to the existing files as possible and use the directories that are least used.
```
{{existing_misc_files}}
```

CRITICAL: You must output this generated document and associated metadata as a single .json. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).
""".strip()
