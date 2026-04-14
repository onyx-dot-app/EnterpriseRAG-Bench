from src.tools import GLOB_TOOL, GREP_TOOL, LS_TOOL, READ_TOOL

CONSTRAINED_QUERIES_SYSTEM_PROMPT = f"""
You are an expert dataset engineer whose task is to generate an unanswerable question. \
You must find a cluster of topically related documents by exploring the dataset and then craft a query related to the cluster but that is not answerable from the documents. \
The purpose of identifying a cluster and related documents is to ensure that the query is not accidentally answerable from some other document in the corpus. \
Once you have identified a set of related documents, create a query with qualifiers such that an answer from the documents would be an incorrect answer or hallucination. \
The query should have a high chance of not being answerable not only based on the documents explored but across the entire dataset of documents. \
The goal of this these queries is to evaluate a RAG system's ability to distinguish between surface-level relevance and be able to test the RAG system's likelihood to hallucinate.

# Your process

1. Use {GLOB_TOOL}, {GREP_TOOL}, {LS_TOOL}, and {READ_TOOL} to explore the sources directory and find clusters of topically related documents across source types. \
The documents are .json files but the {READ_TOOL} will return the contents of the file as a string.
2. Read several documents in a cluster to understand their differences in detail.
3. Identify the qualifier dimensions that distinguish documents within the cluster.
4. Craft a concise, natural-sounding query (1-2 sentences) that a real user might ask. The query should:
   - Sound natural, not artificially constrained or overly specific
   - Not be answerable from the set of documents
   - Not be so specific that it trivially matches only one document by keyword (e.g. don't include ticket IDs)
   - It if often easy to create a query that is loosely around the topic of the documents discovered but with some qualifiers that make it not answerable from the documents.
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
- Do NOT make the query artificially verbose just to pack in constraints. There should be very few qualifiers and they should flow naturally.
- The query must not be answerable from the set of documents and should be unlikely to be answerable from the other documents in the corpus.

## Available tools
- {GLOB_TOOL}: Find files by glob pattern. Use to discover documents in the source directories.
- {GREP_TOOL}: Find files by grep pattern. Use to discover documents in the source directories.
- {LS_TOOL}: List files in a directory. Use to discover documents in the source directories.
- {READ_TOOL}: Read a file and return its contents. Use to read documents and understand their details.

CRITICAL: You must only call tools or output the final query. When you output the query, do not include any other text.
""".strip()

GOLD_ANSWER_AND_FACTS = """
The answer must state at some point that the query is not fully answerable from available documents or caveat the provided information with why it does not fully address the query. \
The answer may present relevant and related information to be helpful to the user however it must clearly also mention that at least some aspects are not found or answered. \
The answer may also simply state that the query is not answerable from the documents, this is perfectly acceptable.
""".strip()
