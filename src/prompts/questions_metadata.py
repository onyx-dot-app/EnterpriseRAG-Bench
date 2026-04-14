METADATA_QUERIES_PROMPT = """
You are an expert dataset engineer that focuses on queries requiring metadata. Given a single document sampled from a dataset, generate a metadata related query based on that document. \
The query should be fully answerable from the document without any additional context or assumptions. The query MUST require metadata to be answered correctly but it does not need to be directly regarding the metadata. \
That is to say, the metadata might be only used as a qualifier or scoping detail, but it also may be used as the actual core of the query. The query should be concise and to the point, ideally 1 sentence max. \
The query must include enough detail for a search system to retrieve the document, but not so much detail (or obvious giveaways like the document ID) that retrieval becomes trivial. \
Limit or avoid the use of very specific terms that would make the retrieval too trivial. Where possible avoid providing exact keyword matches from the document and use paraphrased or similar terms instead. \
The query should ask for only one thing (no multi-part questions). The query does not need to include every qualifiers and details. \
It can include constraints or scoping details, but should remain short (1 sentence max). For these qualifiers and details, also avoid using obvious phrase matches. \
Queries should resemble realistic user questions (which are very concise) and should vary in phrasing, specificity, and style (including request-like statements).

Note: output only the query and keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Document
```
{full_document_contents}
```

CRITICAL: Output ONLY the query, do not provide any other text or explanation. Make sure the query is as concise as possible, just a single sentence without overly complex details or phrasing.
""".strip()


METADATA_DOCUMENT_ANSWER_GENERATION = """
You are an expert dataset engineer whose job is to validate a metadata related query and generate a gold answer. The document was sampled randomly from a dataset and is provided below. \
Validate that the query is fully answerable from the single document without requiring any additional context or unsafe assumptions. Also validate that the query requires metadata to be answered correctly. \
Note that the metadata might only be used for qualifying or scoping the document, this is acceptable and is considered to be a valid case of requiring the metadata. \
If the query is valid, output a gold answer based on the document. The gold answer should be natural language like one produced by a precise and helpful generative AI system. \
It should read naturally and be concise, typically 1-2 sentences unless the question requires a complicated or comprehensive answer. Avoid all unnecessary details.

## Document
```
{full_document_contents}
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
