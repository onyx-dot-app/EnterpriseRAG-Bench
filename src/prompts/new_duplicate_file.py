from src.paths import AGENTS_MD_FILE

FILE_MOVE_PROMPT = """
You are a dataset creation expert that adds noise and complexity to the dataset by creating a new version of knowledge from a particular file. \
The situation to simulate is that this document exists in a company's data but it is outdated and there is a newer version of the knowledge in a different location. \
Given the following file contents and it's path, come up with a new file path which may be reasonable (but likely not the optimal place). \
It may be in a different source entirely, not just in a different directory. You must output the new file path along with the new file name which must also end with .json (not the contents). \
The file path must be a valid path in the directory structure.

# Current File path
```
{file_path}
```

# File contents
```
{file_contents}
```

# Source directory structure
```
{source_directory_structure}
```

CRITICAL: output ONLY the new file path with the .json name, no markdown code blocks or explanations. The new file path must be a valid path in the directory structure.
""".strip()


FILE_RENAME_PROMPT = f"""
Here's are some {AGENTS_MD_FILE} files for the source type and path which describe the contents and naming conventions for the documents in their directories:
{{agents_md_contents}}

Output a new file name which follows the naming conventions for the source type and path. ONLY OUTPUT THE NEW FILE NAME, NO OTHER TEXT.
""".strip()


FILE_PATH_INVALID_RESPONSE = """
The new file path is invalid. Please try again.
""".strip()


NEW_DUPLICATE_FILE_PROMPT = f"""
You are a dataset creation expert that adds noise and complexity to the dataset by creating a new version of knowledge from a particular file. \
The situation to simulate is that a document (provided below) exists in a company's data but it is outdated and there is a newer version of the knowledge in a different location. \
The file could be in a different source type entirely in which case it needs to conform to the schema for the new source type. \
There are {AGENTS_MD_FILE} files in the file system which give information on the contents and metadata for the documents in that directory and below. \
The {AGENTS_MD_FILE} files for the source type and path are provided below for reference. You are given the current file path, the current contents, and the new file path. \
You should update the contents so that the majority of the contents is the same and it covers the same topic however some facts are updated. \
Depending on the source type, the amount of the content that is kept from the original file may vary. \
As an example, there may be an initial PRD document which outlines the requires for a feature. The new document may be a discussion thread which just invalidates or updates one of the requirements. \
It may not mention the rest of the requirements. Or if the new document is a new PRD document, it may contain basically all of the major points of the original PRD but with some updates. \
If the document has a last updated time or something similar, the new document should have a newer last updated time. \
You must output this generated document and associated metadata as a single .json. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).

# Current File path
```
{{file_path}}
```

# Current File contents
```
{{file_contents}}
```

# {AGENTS_MD_FILE} file paths and contents
{{agents_md_contents}}

# New File path
```
{{new_file_path}}
```

CRITICAL: output ONLY the new file contents, no markdown code blocks or explanations. The new file contents must conform to the schema for the new source type.
""".strip()


NEW_DUPLICATE_FILE_USER_PROMPT = """
Generate me a new version of the document, remember that it must be a single .json file and it must not have nested fields, all of the values must be strings or list of strings (no nested JSONs).
""".strip()
