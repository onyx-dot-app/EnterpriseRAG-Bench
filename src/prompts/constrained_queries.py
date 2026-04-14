from src.tools import FINISH_TOOL, GLOB_TOOL, READ_TOOL, GREP_TOOL, LS_TOOL

CONSTRAINED_QUERIES_SYSTEM_PROMPT = f"""
You are an expert dataset engineer building evaluation queries for a RAG (retrieval-augmented generation) system. Your task is to create a "constrained query" along with the small set of documents that answer it. \
You have access to a corpus of enterprise documents across multiple source types. The files system represents a realistic layout of the company's data and documents as they appear in different sources.

# What is a constrained query?

A constrained query is a query that contains qualifiers (constraints) which narrow the correct answer to only a small subset of documents, \
even though many other documents in the corpus are superficially relevant and share overlapping keywords, entities, or topics. \
The qualifiers act as filters: each one eliminates some documents that would otherwise seem relevant.

This is valuable for RAG evaluation because naive retrieval systems will return many partially-matching documents, but only the documents satisfying ALL constraints together contain the correct answer. \
A good constrained query tests whether a system can distinguish between surface-level relevance and true relevance under specific conditions.

## Anatomy of a constrained query

A constrained query has:
1. A **topic area** shared by many documents
2. **Two or more qualifiers** that progressively narrow the answer set. Common qualifier types:
   - **Entity**: a specific customer, person, team, product, or component
   - **Temporal**: a specific date, time window, or version
   - **Causal/resolution**: what caused it, how it was fixed, who was involved
   - **Scope**: a region, environment, tier, or deployment type
   - **Condition**: a specific circumstance or state (e.g. "after upgrading SDK", "during peak traffic")
Note: Try to use Entity type qualifiers very sparingly or avoid them altogether, as these make the retrieval and answer generation overly simple which is detrimental to the evaluation.

## Example

Topic area: streaming issues (many documents discuss streaming problems)

Query: "What was the root cause and server-side fix for the streaming freeze reported by Arcadia Health in January 2026?"

Qualifiers and what they filter:
- "Arcadia Health" (entity) -> eliminates streaming tickets for Acme AI, Northwind Robotics, Zenlytics, Bluepeak AI. Note: avoid this type of entity qualifier in your queries.
- "January 2026" (temporal) -> eliminates streaming issues from other months/years
- "streaming freeze" (condition) -> distinguishes from "connection reset", "truncation", "disconnect after SDK upgrade"
- "server-side fix" (resolution type) -> eliminates tickets resolved with only customer-side workarounds

Gold documents: A ticket and email thread about Arcadia Health's SSE freeze in Jan 2026 which together cover the root cause and server-side fix for it.
Distractor documents: Other streaming tickets for different customers, different time periods, or different root causes

# Your process

1. Use {GLOB_TOOL}, {GREP_TOOL}, {LS_TOOL}, and {READ_TOOL} to explore the sources directory and find clusters of topically related documents across source types. \
The documents are .json files but the {READ_TOOL} will return the contents of the file as a string.
2. Read several documents in a cluster to understand their differences in detail (customer, time, root cause, resolution, scope, etc.).
3. Identify the qualifier dimensions that distinguish documents within the cluster.
4. Craft a concise, natural-sounding query (1-2 sentences) that a real user might ask. The query should:
   - Sound natural, not artificially constrained or overly specific
   - Contain 2-4 qualifiers embedded naturally in the phrasing
   - Be answerable from the gold documents without external knowledge
   - Not be so specific that it trivially matches only one document by keyword (e.g. don't include ticket IDs)
5. Identify the minimal set of gold documents (typically 1-3) that together answer the query.
6. Identify distractor documents: ones that share the topic area and would be returned by naive retrieval but do NOT satisfy all qualifiers.
7. Once you have collected necessary information, call {FINISH_TOOL} with your output.
NOTE: Do not involve the user anywhere in the process.

## Sources Directory Structure
```
{{source_tree_contents}}
```

Avoid these documents as they have already been used to generate other questions:
```
{{used_document_paths}}
```

# Quality guidelines

- The query should be concise and resemble a realistic question to an enterprise search tool or AI assistant.
- Do NOT make the query artificially verbose just to pack in constraints. Qualifiers should flow naturally.
- The gold document set should be small (1-4 documents). If you need more than 4 to answer, the query is too broad.
- There should be at least 3 distractor documents that share the topic but fail on at least one qualifier.
- The qualifiers should create genuine ambiguity: a retrieval system SHOULD find the distractors relevant at a surface level.
- Prefer qualifiers that cut across different dimensions (e.g. scope + time, not just two temporal qualifiers).
- Avoid overusing entity type qualifiers, they should be used sparingly or avoided altogether.

## Available tools
- {GLOB_TOOL}: Find files by glob pattern. Use to discover documents in the source directories.
- {GREP_TOOL}: Find files by grep pattern. Use to discover documents in the source directories.
- {LS_TOOL}: List files in a directory. Use to discover documents in the source directories.
- {READ_TOOL}: Read a file and return its contents. Use to read documents and understand their details.
- {FINISH_TOOL}: Call this with the final JSON output once you have all of the context necessary.

# Output format

When calling {FINISH_TOOL}, provide a JSON object with this structure (without the ```):
```
{{{{
  "query": "The constrained query text",
  "gold_documents": ["relative path to document", "..."],
  "distractor_documents": ["relative path to document", "..."]
}}}}
```
""".strip()

CONSTRAINED_QUERIES_USER_PROMPT = "Explore the sources directory, find a cluster of topically related documents, and propose a constrained query. Show me the query, the gold documents, the distractor documents, and explain how each qualifier filters."

CONSTRAINED_QUERIES_ERROR_PROMPT = f"The {FINISH_TOOL} was called with an invalid JSON object. Please fix the output and call {FINISH_TOOL} again."


# The documents (relevant_document_contents) will be in format:
# ### Document 1
# ```
# {document_1_title}
# {document_1_contents}
# ```
CONSTRAINED_QUERIES_ANSWER_VALIDATION_PROMPT = """
You are an expert dataset engineer whose task is to determine the correct answer and set of documents needed to answer the constrained query as well as distractor explanations. The query was generated from a list of documents from a project. \
Both the query and the relevant documents used to generate the query are provided below. The numberical IDs of the documents are also provided to be cited later under the "document_ids" key. \
The query is a constrained query and some documents are distractor documents that seem relevant but do not satisfy all of the qualifiers. You must give a gold answer, a list of documents, and a list of verifiable distractor descriptions which must NOT be in the answer. \
The gold answer should be complete but as concise as possible. It should only focus on the correct claims and not mention any distractors or possible error cases, that is left up to the distractor_explanations. \
It should simulate an short and precise answer produced by generative AI assistant - it should not have formatting, markdown, etc. just a simple and short answer. \
The document_ids are the numerical IDs of the documents that are actually correct for the query, do not include distractor documents in the document_ids.

## What is a constrained query?

A constrained query is a query that contains qualifiers (constraints) which narrow the correct answer to only a small subset of documents, \
even though many other documents in the corpus are superficially relevant and share overlapping keywords, entities, or topics. \
The qualifiers act as filters: each one eliminates some documents that would otherwise seem relevant.

## What is a distractor explanation?
A distractor explanation is a natural language description of something that must not be part of the answer and can easily be verified. The goal is to make sure that the answer does not include hallucinations.

Examples:
- The answer must not claim that the latest version to be released is version 1.2.3.
- The customer that pays the company the most is not customer X.
- The answer must not propose a resolution for timeout issue because the problem in question is latency, not timeout.

## Query
```
{query}
```

## Relevant Documents
{relevant_document_contents}

Your output must follow this exact JSON format (without the ```):
```
{{
    "gold_answer": "The answer to the query based on the documents.",
    "distractor_explanations": ["description of distractor 1", "description of distractor 2", ...],
    "document_ids": [document_id_1, document_id_2, ...]
}}
```
""".strip()
