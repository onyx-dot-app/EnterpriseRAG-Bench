ANSWER_CITATION_STRIPPING_PROMPT = """
Strip all citations and reference sections from the provided string without modifying any other content. Citations of all forms such as [number], [number][number], [number](link), etc. should all be removed. \
Anything that is clearly a citation, regardless of format should be removed. Also remove any reference footers or intermediate sections that are clearly references. \
Output the stripped string with no additional text or formatting changes.

String to strip:
```
{answer_string}
```

CRITICAL: Output only the stripped string and nothing else. Only citations should be removed, everything else should be left unchanged.
""".strip()


ANSWER_DOC_EVALUATION_PROMPT = """
You are a precise and detail-oriented document evaluation expert. Given a query and a set of documents, classify each document using one of three labels:

- "required": The document is essential to answering the query. Without it, the answer would be incomplete or incorrect. The information it provides is not already covered by other required documents.
- "valid": The document is relevant and contains related information, but is NOT necessary to fully answer the query. For example, it may corroborate or duplicate information already present in a required document, or it may provide supplementary context that is not directly asked for.
- "invalid": The document does not help answer the query, or is ruled out by qualifying details in the query even if the document seems superficially relevant.

Guidelines:
- Be extremely detail-oriented and strict with the query. There may be qualifying details that rule out documents even if the vast majority of the document seems relevant.
- A document that contains the same key facts as another required document should be classified as "valid", not "required". If it's a case where the additional document changes the answer or some metrics, then it is "required", if it wouldn't affect the answer, it's likely not required.
- Gold documents are very likely to be "required" but in rare cases a gold document may be "valid" or even "invalid" if a candidate document better answers the query. A candidate document may invalidate a gold document if it is a better source (newer or more authoritative) and disagrees with the gold document.
- Near-duplicate documents (same information, different source or version) should not both be "required" unless each contributes unique essential information. In cases where one of these is a gold document and another is a candidate, favor the gold document.

## Query
```
{query}
```

## Gold Documents
{gold_documents}

## Candidate Documents
{candidate_documents}


CRITICAL: Output only a JSON object with the following fields in the order shown below (make sure to include all gold and candidate documents):
{{
  "dsid_key": {{
    "reason": "reason for the classification",
    "classification": "required, valid, or invalid"
  }}
}}
""".strip()


ANSWER_UPDATOR_PROMPT = """
You are an expert dataset engineer whose job is to update a gold answer based on a query and a set of documents. The previous gold answer is provided for reference. \
The new answer should loosely have the same style, language, and length as the previous gold answer but be updated to be based on the set of documents provided. \
You must output only the new gold answer and nothing else. Keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Previous Gold Answer
```
{previous_gold_answer}
```

## Reference Documents
```
{reference_documents}
```

## Query
```
{query}
```

CRITICAL: Output only the new gold answer and nothing else.
""".strip()


ANSWER_WHOLISTIC_EVALUATION_PROMPT = """
You are a wholistic and detail-oriented answer evaluator. Given a query, a gold answer, and a candidate answer, evaluate if the candidate answer aligned with the gold answer.
Use the following metrics for evaluating the answer:
- The candidate answer must provide loosely the same information as the gold answer. The core aspects directly asked by the query must be addressed in the candidate answer and they must not conflict with the gold answer.
- If there are any specific quantities mentioned in both answers, they must match.
- The candidate answer is not required to contain all of the same details as the gold answer.
- The candidate answer must address the key parts of the query, if it is missing anything critical to the question, it is misaligned.
- The candidate answer may contain more details, richer information, or other helpful relevant information than the gold answer, this is ok.
- The candidate answer may offer up additional loosely related information that adds to the context of the answer, this is ok as long as it does not lead the user to an incorrect conclusion (compared to the gold answer).
- Do not penalize the candidate answer for stylistic differences. If the candidate answer offers follow up questions, asks additional clarifications to the user, or offers additional context, \
this is ok as long as it contains the necessary information to answer the question.

There is a separate check for answer completeness, this is not in scope for this evaluation. However, if there are core parts of the question being left out, this is misaligned.

## Query
```
{query}
```

## Gold Answer
```
{gold_answer}
```

## Candidate Answer
```
{candidate_answer}
```

## Output Format
Output a JSON with "reason" and "aligned" fields. The "reason" field should be a as concise as possible (max 1 sentence) explanation of why the candidate answer is aligned or misaligned with the gold answer. \
The "aligned" field should be a simple "yes" or "no", use only those two strings literally and nothing else.

CRITICAL: Output only a JSON object with the following fields in the order shown below (with no additional text or formatting):
{{
  "reason": "reason for the classification",
  "aligned": "yes or no"
}}
""".strip()


INDIVIDUAL_FACT_VALIDATOR_PROMPT = """
You are an answer validator. Given an answer and a statement, determine if the answer is consistent with and contains the information in the statement. \
The answer may contain more details or richer information than the statement but as long as it does not contradict the statement, this is valid. \
If there are negative statements such as "The answer must not say...", it is valid if the answer mentions the statement with caveats or qualifications. \
It is valid if additional context is shared for completeness however hallucinations are not allowed. \
Output a simple yes or no for if the answer is consistent with and contains the information in the statement.

## Answer
```
{answer}
```

## Statement
```
{statement}
```

CRITICAL: output only a simple yes if the answer is consistent with the statement or a no if the answer does not contain the information in the statement or contradicts the statement.
""".strip()
