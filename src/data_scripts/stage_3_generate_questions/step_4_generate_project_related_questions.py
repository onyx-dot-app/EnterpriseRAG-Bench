PROJECT_RELATED_QUERIES_PROMPT = """
You are an expert dataset question generation engineer. Given a list of documents from a project, generate an interesting query that is related to the project. \
See below for things that make a query interesting. These are not requirements but examples that may help you generate an interesting query.

# Query characteristics

## Multi-document
- Cross-document entity joins: queries correlating some distinct entities across different documents or tracking relationships across documents.
- Multi-document: queries where the answer takes parts from multiple documents to build a cohere picture of the answer.
- Cross-format joins: requiring different document categories such as meeting notes + PRDs + code changes + customer communications.
- Multi-hop: one step and information is needed to know what is needed next to answer the question. Requires a chain of successful searches and inferences based on the results to answer the question.

## Complexity
- Disambiguation: queries that require disambiguation through incremental discovery of information.
- Time/version awareness: queries that require resolving temporal changes using multiple docs that span time or versions.
- Tradeoffs: answers that require justifications and comparisons between options mentioned in different source documents
- Contradictions: conflicting information and requiring a good answer to mention the contraditions and reconciling them.
- Operational reality: queries that require combining product intent (PRD/requirements) with operational reality. Was the goal achieved, where are the remaining gaps?
- Evidence: queries that require showing the path and work needed to justify the answer.


Note: output only the query and keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Document
```
{document_title}
{document_contents}
```

CRITICAL: Output ONLY the query, do not provide any other text or explanation.
""".strip()