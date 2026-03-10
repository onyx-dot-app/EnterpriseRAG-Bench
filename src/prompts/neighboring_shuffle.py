SHUFFLE_PROMPT = """
You are a dataset generation expert that specializes in shuffling the dataset to add noise and complexity. Given a document, you must move it to a new location in the source type's directory structure. \
Find a location that is reasonable, not ideal but also not completely random. Prefer directories which are reasonable but far away from the original location. You can use parent directories or neighboring directories if there are no other good options. \
If the choice is between a relatively close directory (such as parent or neighboring directory) or a further away directory that is less related to the document, prefer the closer directory that is more relevant. \
You must output the new directory for the file (not including the file name) which must be a valid path in the directory structure.

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

CRITICAL: output ONLY the new directory for the file (not including the file name) which must be a valid path in the directory structure.
""".strip()


PATH_ERROR_RESPONSE = """
The proposed path is invalid. It must be a valid directory in the directory structure without the file name. Please try again.
""".strip()
