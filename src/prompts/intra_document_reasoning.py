INTRA_DOCUMENT_REASONING_PROMPT = """
You are an expert dataset question generation engineer. Given a single document sampled from a dataset, generate an intra-document reasoning query based on that document. \
An intra-document reasoning query is a query that requires information from multiple parts of the document to answer. Specifically it should take information from the beginning and end of the document and possibly some information from the middle. \
As a hypothetical example, a bottom section may talk about a particular topic like "the pricing per license per month is $100" and the top section may mention "we'll go over the pricing later which is unique to the AMEA region". \
A good intra-document reasoning query would be "What is the pricing per license per month for the AMEA region?". A retrieval system which is only able to fetch sections of the document would not be able to answer this question, which makes it a good intra-document reasoning query. \
The query should be fully answerable from the document without any additional context or assumptions. \
The query must include enough detail for a search system to retrieve the document, but not so much detail (or obvious giveaways like the document ID) that retrieval becomes trivial. \
The query does not need to include every qualifiers and details (see example 1 below). It can include constraints or scoping details, but should remain short. \
Queries should resemble realistic user questions or requests to an LLM-powered enterprise search tool, and should vary in phrasing, specificity, and style (including request-like statements).

Note: output only the query and keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Examples
Example 1 (bad): Why does the Hosted API return 403 Forbidden with “Not authorized” when calling POST /v1/api-keys/{{key_id}}/rotate after enabling RBAC v2 (deny-by-default), and what permission or role mapping change fixes it for legacy “Org Admin” users?
  - The query has too many parts, mentions not only the error but also permissions, roles, and fixes with additional qualifying details.
  - It is not necessary to include both qualifiers of "when calling POST /v1/api-keys/{{key_id}}/rotate" and "after enabling RBAC v2 (deny-by-default)", typically users will not provide this level of detail.
  - Stopping at the first comma would make this a good query.

Example 2 (bad): Where can I find the refreshed Support/CS escalation playbook in Confluence, and what's the expected adoption date for using it on new SUP tickets/bridges?
  - The query is too long and detailed and also multipart.
  - Should be reframed instead as "What's the expected adoption date for the refreshed Support/CS escalation playbook?"

Example 3 (bad): List the POC scope and acceptance targets for Conversio Cloud's 4-week hosted API pilot with Redwood (including concurrency, token volume, first-token latency, and allowed streaming failure rate).
  - Too detailed and specific. Even not considering the things in the parenthesis, the query is still too specific.
  - Note that the variation in language here (using "list" instead of "what") is a good example of how the query should vary in style.

Example 4 (good): For Seaside Streetwear's demo request, what latency target did they quote?
  - This is a good query because it is concise and to the point while providing enough detail that the document can be found by a search system.
  - This is also a good example of a query that is phrased slightly differently since it starts with "For Seaside Streetwear's demo request".

## Document
```
{document_title}
{document_contents}
```

CRITICAL: Output ONLY the query, do not provide any other text or explanation. Ensure that the query requires reasoning across information from at least near the top and bottom of the document to answer.
""".strip()
