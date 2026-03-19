CONFLICTING_INFO_PROMPT = """
You are a precise dataset generation expert whose task is to come up with a query that requires correctly identifying conflicting or outdated information within the document corpus. \
Given a set of two documents from that document corpus which are related, come up with a query, a corresponding gold answer, and a list of verifiable statements about the answer. \
The documents may be similar or updated versions of each other. If possible, the query should be around an area of the document where the two documents differ in information. \
The query should be as concise as possible (ideally a single short sentence) but include a small amount of detail (as minimal as possible) so that a search system can retrieve the correct documents. \
If one of the documents is a clear update or revision of the other document, the gold answer should reflect the updated information. If the user should be aware of the older information, it should be included in the gold answer as well. \
If the user only requires the latest information and the older information is not obviously informative, then do not include the older information in the gold answer. \
The list of verifiable statements should include both the facts that should exist in a good candidate answer for the query, and statements that ensure hallucinations are penalized. \
For example, one such statement might be "The answer may mention that a previous pricing of $25 was proposed but it must state that the final pricing was $20". \
IMPORTANT: keep all of the output fields (query, gold answer, verifiable statements) as concise as possible.

Output a JSON object with the following fields:
- query: the query string
- gold_answer: the gold answer string
- verifiable_statements: the list of verifiable statements

## Document 1
{document_1}

## Document 2
{document_2}

# Output Format
{{
    "query": "the query string",
    "gold_answer": "the gold answer string",
    "verifiable_statements": ["the list of verifiable statements", "remember to include statements that penalize hallucinations"]
}}
""".strip()
