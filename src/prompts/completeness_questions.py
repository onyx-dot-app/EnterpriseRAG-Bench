COMPLETENESS_DOC_EVALUATION_PROMPT = """
You are a precise and detail-oriented document evaluation expert. Given a query and a set of documents, evaluate which candidate documents contain necessary information for answering the query. \
These are completeness questions — the goal is to identify EVERY document that a thorough retrieval system should return to give a complete and correct answer to the question. \
A document is "required" if it contains facts, data points, discussion, or context that adds to the answer and is not made redundant by another document. When in doubt, classify as "required".

You must output only a JSON object with the following fields (make sure to include all candidate documents):
- The dsid_key which is the unique identifier of the document, include a classification and reason for every candidate document provided below.
- Within this dsid_key, include both a "classification" which must be either "required" or "unnecessary" and a "reason" for the classification which is a short justification for the classification.

## Query
```
{query}
```

## Candidate Documents
{candidate_documents}

CRITICAL: Output only a JSON object with the following fields (make sure to include all candidate documents):
{{
  "dsid_key": {{
    "classification": "required or unnecessary",
    "reason": "reason for the classification"
  }}
}}
""".strip()


COMPLETENESS_ANSWER_GENERATION_PROMPT = """
You are an expert dataset engineer whose job is to generate a gold answer for a provided query. Make sure to provide a comprehensive answer that leverages all of the relevant documents included below. \
It is unlikely that any of the documents are not relevant but if any are not relevant to the query, you may ignore them. The gold answer should be in natural language like one produced by a precise and helpful generative AI system. \
It should read naturally and be concise, typically 1-2 sentences unless the question requires a complicated or comprehensive answer. Avoid all unnecessary details and keep your answer as short as possible while fully answering the query.

## Query
```
{query}
```

## Relevant Documents
{relevant_documents}

CRITICAL: Output ONLY the gold answer as a natural language response, do not provide any other text or explanation.
""".strip()
