FILE_MOVE_PROMPT = """
You are a dataset creation expert that adds noise and complexity to the dataset by creating a new version of knowledge from a particular file. \
The situation to simulate is that this document exists in a company's data but it is outdated and there is a newer version of it in a different location. \
Given the following file contents and it's path, come up with a new file path which may be reasonable (but likely not the optimal place). \
It may be in a different source entirely, not just in a different directory.

# File contents
```
{file_contents}
```

# File path
```
{file_path}
```

# Source directory structure
```
{source_directory_structure}
```

CRITICAL: output ONLY the new file path, no markdown code blocks or explanations. The new file path must be a valid path in the directory structure.
""".strip()