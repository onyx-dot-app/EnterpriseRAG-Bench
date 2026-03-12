from src.tools import READ_TOOL


PROJECT_RELATED_QUERIES_PROMPT = f"""
You are an expert dataset question generation engineer. Given a list of documents from a project, generate an interesting query that is related to the project. \
See below for things that make a query interesting. These are not requirements/exhaustive but instead just examples that may help you generate an interesting query. \
You have the {READ_TOOL} to read the document contents and use the information to generate the query. \
The query must be concise and to the point. Try to aim for 1-2 sentences that does not contain significant details, qualifiers, or modifiers. \
This should simulate how a real user would ask a query to an AI system or coworker. Do not try to chain together all of the documents for an interesting query. \
It is best if the query requires several documents to answer but it is more important that the query is focused and clear rather than a mix of different directions from a lot of different documents.

# Query characteristics

## Multi-document
- Cross-document entity joins: queries correlating some distinct entities across different documents or tracking relationships across documents.
- Multi-document: queries where the answer takes parts from multiple documents to build a cohere picture of the answer.
- Cross-format joins: requiring different document categories such as meeting notes + PRDs + code changes + customer communications.
- Multi-hop: incremental steps and information are needed to know what is needed next to answer the question. Requires a chain of successful searches and inferences based on the results to answer the question.
- Comparison & contrast: queries that require comparing and contrasting different options, approaches, solutions and information coming from different documents.
- Cross-cutting: items mentioned incidentally across multiple documents but are never the primary focus of any single document.

## Complexity
- Disambiguation: queries that require disambiguation through incremental discovery of information.
- Time/version awareness: queries that require resolving temporal changes using multiple docs that span time or versions.
- Tradeoffs: answers that require justifications and comparisons between options mentioned in different source documents
- Contradictions: conflicting information and requiring a good answer to mention the contraditions and reconciling them.
- Operational reality: queries that require combining product intent (PRD/requirements) with operational reality. Was the goal achieved, where are the remaining gaps?
- Evidence: queries that require showing the path and work needed to justify the answer.
- Causal chain: tracing a cause and effect relationship through multiple documents to create a cohere story.

## Example Archetypes
These are only examples for inspiration. Do not use these directly. It is better to also mix and combine these (or others) with additional characteristics to generate an interesting query.
- Root cause + remediation
- Implementation vs requirements gap
- Migration readiness / progress
- Ownership + escalation path + historical context
- Customer specific behavior or lifecycle

Note: output only the query and keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Project Overview
{{project_overview}}

## Project Document
```
{{project_document_paths}}
```

CRITICAL: Use the {READ_TOOL} to read the document contents and use the information to generate the query. After you are finished reading documents, output ONLY the query, do not provide any other text or explanation.
""".strip()


# The documents (project_document_contents) will be in format:
# ### Document 1
# ```
# {document_1_title}
# {document_1_contents}
# ```
PROJECT_RELATED_QUERIES_ANSWER_VALIDATION_PROMPT = """
You are an expert dataset engineer whose task is to determine the minimal set of documents needed to answer the project related query. The query was generated from a list of documents from a project. \
Both the query and the project documents used to generate the query are provided below. The numberical IDs of the documents are also provided to be cited later under the "document_ids" key. \
The answer should be complete but as concise as possible. It should simulate an short and precise answer produced by generative AI assistant - it should not have formatting, markdown, etc. just a simple and short answer.

## Query
```
{query}
```

## Project Documents
{project_document_contents}

Your output must follow this exact JSON format (without the ```):
```
{{
    "gold_answer": "The answer to the query based on the documents.",
    "document_ids": [document_id_1, document_id_2, ...]
}}
```
"""
