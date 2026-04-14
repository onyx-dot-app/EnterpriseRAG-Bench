SINGLE_DOCUMENT_ANSWER_GENERATION = """
You are an expert dataset engineer whose job is to validate a query and generate a gold answer. The document was sampled randomly from a dataset and is provided below. \
Validate that the query is fully answerable from the single document without requiring any additional context or unsafe assumptions. Also validate that the query is meaningful. \
For example, if the document is just small talk and the query does not contain any information which would be useful to a real user from the company, then the query is not valid. \
If the query is valid, output a gold answer based on the document. The gold answer should be natural language like one produced by a precise and helpful generative AI system. \
It should read naturally and be concise, typically 1-2 sentences unless the question requires a complicated or comprehensive answer. Avoid all unnecessary details.

## Document
```
{document_title}
{document_contents}
```

## Query
```
{query}
```

# Output Format
Note that if valid is false, the gold_answer should just say N/A.
{{
  "valid": false,
  "gold_answer": "N/A"
}}

CRITICAL: Output ONLY the JSON object, do not provide any other text or explanation.
""".strip()


INTRA_DOCUMENT_REASONING_ANSWER_GENERATION = """
You are an expert dataset engineer whose job is to validate an intra-document reasoning query and generate a gold answer. The document was sampled randomly from a dataset and is provided below. \
An intra-document reasoning query is a query that requires information from multiple parts of the document to answer. Specifically it should take information from the beginning and end of the document and possibly some information from the middle. \
Verify that the query is a valid intra-document reasoning query. If the question is fully answerable from a single section of the document, then the query is not valid. \
If the query is valid, output a gold answer based on the document. The gold answer should be natural language like one produced by a precise and helpful generative AI system. \
The answer should be straightforward and only address the query - it does not need to use all of the relevant parts of the document. \
It should read naturally and be concise, typically 1-2 sentences unless the question requires a complicated or comprehensive answer. Avoid all unnecessary details.

## Document
```
{document_title}
{document_contents}
```

## Query
```
{query}
```

# Output Format
Note that if valid is false, the gold_answer should just say N/A.
{{
  "valid": false,
  "gold_answer": "N/A"
}}

CRITICAL: Output ONLY the JSON object, do not provide any other text or explanation.
""".strip()
