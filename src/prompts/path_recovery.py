PATH_RECOVERY_PROMPT = """
An LLM output the following incorrect path:
```
{incorrect_path}
```

Here is a tree of the valid paths:
```
{valid_paths_tree}
```

Recover the correct path or find the closest valid path. It should start with 'sources/' and end with the file (including extension).
""".strip()
