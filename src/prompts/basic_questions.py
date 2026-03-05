BASIC_QUESTIONS_PROMPT = """
You are an expert dataset engineer whose job is to generate a question based off of a document. The document was sampled randomly from a dataset and is provided below. \
The question should be fully answerable from the single document without any additional context or assumptions required. \
The question must contain enough information and detail that the document can reasonably be found by a search system. On the other hand, it should also not be so detailed and specific that it becomes trivial for a search system to find the document. \
Avoid multi-part questions (explained below) and be concise. There can be qualifying or scoping details but it should not be long. This simulates how users want fast access to information and do not want to type too much. \
The question should be meaningful and realistic, it should be a question that a user at the company might actually ask. The questions should vary in style, detail, and complexity, similar to how users might ask questions to a real LLM based search system. \
It is encouraged that some questions are phrased more like requests/statements (see examples below).
Note: keep the character set of the questions simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

# Examples:
Example 1: Why does the Hosted API return 403 Forbidden with “Not authorized” when calling POST /v1/api-keys/{{key_id}}/rotate after enabling RBAC v2 (deny-by-default), and what permission or role mapping change fixes it for legacy “Org Admin” users?
  - This is bad because the question has too many parts, mentions not only the error but also permissions, roles, and fixes with additional qualifying details.
  - Stopping at the first comma would make this a good question.

Example 2: Where can I find the refreshed Support/CS escalation playbook in Confluence, and what's the expected adoption date for using it on new SUP tickets/bridges?
  - This is ok because even though it has two parts, they are fairly connected and there are not too many unnecessary details.
  - Stopping at the first comma would be preferred.

Example 3: List the POC scope and acceptance targets for Conversio Cloud's 4-week hosted API pilot with Redwood (including concurrency, token volume, first-token latency, and allowed streaming failure rate).
  - This is bad because it is too detailed and specific. The question should not include the things in the parenthesis. Removing the parenthesis contents would make this a good question.
  - Note that the variation in language here (using "list" instead of "what") is a good example of how the question should vary in style.

Example 4: For Seaside Streetwear's demo request, what latency target did they quote?
  - This is a good question because it is concise and to the point while providing enough detail that the document can be found by a search system.
  - This is also a good example of a question that is phrased slightly differently since it starts with "For Seaside Streetwear's demo request".

Example 5: Describe the mitigation plan and due date for the high-severity SEC-4123 OpenSSL vulnerability affecting serving-runtime images built from base v2026-01, as discussed in the Security Engineering Sync notes from 2026-03-17.
  - This is bad because the question is so specific that retrieving the document becomes trivial.
  - Stopping before the "as discussed" would make this a good question.
  - This is a good example of variations in language since it starts with "Describe" instead of "What".

## Document
```
{document_title}
{document_contents}
```

CRITICAL: Output ONLY the question, do not provide any other text or explanation.
""".strip()


BASIC_QUESTION_VALIDATION = """
You are an expert dataset engineer whose job is to validate a question based off of a document. The document was sampled randomly from a dataset and is provided below. \
Validate that the question is fully answerable from the single document without requiring any additional context or unsafe assumptions. \
You should also validate that the question is meaningful. For example, if the document is just smalltalk and the question does not contain any information which would be useful to a real user from the company, then the question is not valid. \
If the question is valid, also output what the expected answer must contain. Importantly, do not give the expected answer, give a description of what the expected answer should contain or not contain. \
This description will later be used to validate if a candidate answer is correct or not. The description should be 1-2 sentences max (keep it as concise and information dense as possible).

## Document
```
{document_title}
{document_contents}
```

## Question
```
{question}
```

# Output Format
Note that if valid is false, the expected_answer_explanation should just say N/A.
{{
  "valid": false,
  "expected_answer_explanation": "N/A",
}}

CRITICAL: Output ONLY the JSON object, do not provide any other text or explanation.
""".strip()