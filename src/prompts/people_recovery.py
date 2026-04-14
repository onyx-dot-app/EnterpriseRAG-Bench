PEOPLE_RECOVERY_PROMPT = """
An LLM output the following project overview:
```
{project_overview}
```

Employee Directory:
```
{employee_directory}
```

The user `{user_name}` was added to the project but does not exist in the employee directory. Who would be the correct person to replace them?
CRITICAL: Only provide the name of the person, nothing else.
""".strip()
