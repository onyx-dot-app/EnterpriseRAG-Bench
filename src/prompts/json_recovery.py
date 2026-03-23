JSON_RECOVERY_PROMPT = """
You are a precise JSON recovery expert. Given the following broken JSON string, output a correct/fixed JSON string. \
Common error cases include the inclusion of control characters or missing escape characters. \
You must keep the contents as faithful as possible to the original JSON string, only fixing errors.

Broken JSON string:
```
{broken_json_string}
```

CRITICAL: Output ONLY the corrected/fixed JSON string, do not wrap it in markdown code blocks or provide any explanations.
""".strip()
