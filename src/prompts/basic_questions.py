BASIC_QUERIES_PROMPT = """
You are an expert dataset engineer. Given a single document sampled from a dataset, generate a query based on that document. The query should be fully answerable from the document without any additional context or assumptions. \
The query must include enough detail for a search system to retrieve the document, but not so much detail (or obvious giveaways like the document ID) that retrieval becomes trivial. \
Limit or avoid the use of very specific terms that would make the retrieval too trivial. Where possible avoid providing exact keyword matches from the document and use paraphrased or similar terms instead. \
The query should ask for only one thing (no multi-part questions unless the second part is the actual question of interest and the first part is a necessary qualifier). \
The query does not need to include every qualifiers and details (see example 1 below). It can include constraints or scoping details, but should remain short. For these qualifiers and details, also avoid using obvious phrase matches. \
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

CRITICAL: Output ONLY the query, do not provide any other text or explanation.
""".strip()


SEMANTIC_QUERIES_PROMPT = """
You are an expert dataset engineer whose task is to generate a difficult RAG query that does not have strong lexical matches to the document. Whenever possible, avoid using exact keyword matches from the document. \
Given a single document sampled from a dataset, generate a semantic query based on that document which can be used to retrieve the document and answer the query. \
It should simulate a situation where a user does not have the document in front of them and therefore cannot provide a strong lexical/keyword match to the document. Strongly limit or avoid the use of specific terms that would make the retrieval easy. \
The query must include enough detail for a search system to reasonably be able to retrieve the document and specific enough that it is unlikely for other documents to provide an equally correct answer. \
The query should ask for only one thing, avoid multi-part questions and avoid overusing qualifying details. The query can include some constraints or scoping details but it should not need to include every qualifiers and details (see example 1 below). \
Queries should resemble realistic user questions or requests to an LLM-powered enterprise search tool. It is encouraged for the query to show variance in phrasing, specificity, and style (including request-like statements).

CRITICAL: This is intended to be a more challenging, loose match, semantic type query for a dataset compared to a basic natural language query. Intentionally make these challenging. Strongly limit your use of exact terms and phrase matches.

Note: output only the query and keep the character set simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

## Examples
Example 1 (bad): Why does the Hosted API return 403 Forbidden with “Not authorized” when calling POST /v1/api-keys/{{key_id}}/rotate after enabling RBAC v2 (deny-by-default), and what permission or role mapping change fixes it for legacy “Org Admin” users?
  - The query has too many parts/asks, mentions not only the error but also permissions, roles, and fixes with additional qualifying details.
  - There are way to many qualifiers and details in the query, typically users will not provide this level of detail and this makes the search trivial.
  - The query has a lot of specific high lexical match terms like /v1/api-keys/{{key_id}}/rotate, RBAC v2 (deny-by-default), etc.
  - The query can be improved to: "Why does the Hosted API return a not authorized error when calling the key rotation endpoint after enabling role based access?"
    - This is now much more concise and similar to how a user would actually ask a question.
    - The match is still quite obvious but now a much fuzzier match and with fewer direct phrase overlaps.

Example 2 (bad): What is the on prem backup and audit log retention approach for a healthcare deployment of a private AI platform, including envelope encryption with customer managed HSM keys, what gets backed up vs cluster recovery, and what evidence or reports are available for auditors (restore validation, manifests, log export schema)?
  - The query is too long and detailed. A query should not have many parts like this.
  - The query can be improved to: "How are backups and audit logs preserved for privacy first AI healthcare deployments?"
    - This is now much more concise and similar to how a user would actually ask a question.

Example 3 (bad): What did the team decide should be in v1 vs v1.1 for the Unit Economics dashboard, especially around drilldowns, required dimensions, and whether quantization profile is UI or API only?"
  - The query has too many specifics to be considered a good fuzzy semantic query. The things considered specific here are: "v1 vs v1.1", "Unit Economics dashboard", "drilldowns", "required dimensions", "quantization profile", and "UI or API only". This is way too many details and exact phrase matches.
  - The query can be improved to: "For the econ dashboard, is the quant profile going to be in version 1 or only in >1?"

Example 4 (good): Give me the estimated timeline for SOC 2 compliance as of Jan 2026 and the owners of this effort.
  - This is a concise query and contains enough information to find the relevant document.
  - It avoids exact phrase matches like "SOC 2 Type II" or phrases that make the search trivial like "as outlined in the SOC 2 effort estimation doc", etc.
  - It is not overly multi-part and does not include significant qualifying details. It includes some details like "Jan 2026" which will prevent this from matching too many docs and for it to be ambiguous what the right answer is.
  - It is a good example of variation in language, this one is phrased as a request-like statement.

## Document
```
{document_title}
{document_contents}
```

CRITICAL: Output ONLY the query, do not provide any other text or explanation. Ensure this is a challenging semantic / loose match type query.
""".strip()
