HIGH_LEVEL_QUESTIONS_PROMPT = """
You are a precise dataset generation expert whose task is to come up with a set of queries based on high level information about a company. \
Queries must be directly answerable from the high-level information below. The queries should require identifying patterns or synthesizing information across multiple documents within the actual corpus of documents from the company. \
Avoid queries where the answer is likely to be found within a single document in the company's internal corpus. \
The queries should be concise and factual so that they are verifiable from the high-level information below, do not include extraneous information or details. \
The queries should have a spread of topics and types of questions. Each individual query should be a single sentence that asks about a single item. Do not make complex, multipart queries. \
Queries should resemble realistic user questions and should vary in phrasing, specificity, and style (including request-like statements). \
Output a JSON object with integer keys starting from 1 and query strings as values (see Output Format section below).

## Company Overview
{company_overview}

## High level initiatives
{initiatives}

## Output Format
The keys should be the query number (integers starting from 1) and the values should be the query strings.
{{
  "1": "The first example query about the company.",
  "2": "A second query, hopefully with different language/phrasing style.",
  "3": "The third query, exploring a different topic or area of interest.",
  ...
}}
""".strip()


USER_PROMPT = """
Based on the information provided, give me {num_queries} queries. Output only the JSON object and nothing else.
""".strip()


HIGH_LEVEL_QUESTIONS_EVALUATION_PROMPT = """
You are a precise and detail-oriented dataset generation expert. Given a query and a set of documents containing high level information about a company, provide a gold answer. \
The answer should be as concise as possible while answering the query fully. Do not include extraneous information or details. \
Keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Reference Documents
```
{reference_documents}
```

## Query
```
{query}
```

CRITICAL: Output only the gold answer and nothing else.
""".strip()


VALIDATE_NO_POINT_QUERY_PROMPT = """
You are an expert dataset curator. Given a high level query about the company, try to find the answer by traversing and searching across the document set. \
You have access to a set of tools to try to find the answer. If you find a document that directly contains the answer, the query is an invalid "high level" query. \
After checking a small set of reasonable documents which may contain the answer, output "valid" if there hasn't been a direct answer found in a single document.

## Directory Structure
```
{directory_structure}
```

## Available Tools
- {GLOB_TOOL}: Glob for a pattern and return the list of files that match.
- {GREP_TOOL}: Grep for a pattern and return the relevant lines that match.
- {LS_TOOL}: List the contents of a directory.
- {READ_TOOL}: Read the contents of a file.

## Query
```
{query}
```

You must only use tools or output one of the two following options:
"invalid" - if the query has a direct answer found in a single document
"valid" - if the document does not have a single place where it can be answered and would require aggregating information from a multitude of documents.
""".strip()
