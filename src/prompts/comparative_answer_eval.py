IS_GOLD_DOCUMENT_STR = " (gold document, this is one of the document set's expected documents for this question.)"

DOCUMENT_TEMPLATE = """
### Document {number}{is_gold_document_str}

```
{document_title}
{document_contents}
```
"""

# Note, the gold answer is not provided to avoid biasing the LLM for answers that are similar in style and detail to the gold answer.
# All of the relevant information is provided however since all of the expected documents and the ones retrieved by the systems are presented (up to a max document limit per system).
COMPARATIVE_EVAL_PROMPT = """
You are an expert answer evaluator. You will be given a query, two candidate answers from different search systems, and the documents each system retrieved.
Documents retrieved by both systems appear under "Overlapping Documents". Some documents may be labeled as gold documents, but this label does not guarantee they are the best or only documents needed to answer the query — \
other documents may supersede or invalidate them, and gold documents may not appear at all. Evaluate which answer better addresses the query, or whether the two are effectively equivalent. \
Two answers are equivalent when they convey very similar amounts of clearly useful information. Apply the following guidelines:
- Information that is peripherally related or not directly relevant to the query should neither be rewarded nor penalized.
- Related information that is likely helpful to the user should be viewed positively, but related information that could mislead the user should be viewed negatively.
- Do not favor a system for retrieving more documents. Additional documents only matter if the answer draws on them to be more correct or complete.
- It is possible some documents seem relevant but are actually misleading or incorrect.
- Provably incorrect information or unsubstanciated claims based on the provided documents should be strongly penalized.
- Ignore stylistic differences such as helpfulness cues, follow-up suggestions, or formatting.
- If both answers are wrong according to the documents, favor the one that is less misleading.

## Query:

```
{query}
```

## Candidate Answer from System 1

```
{candidate_answer_1}
```

## Candidate Answer from System 2

```
{candidate_answer_2}
```

## Overlapping Documents

These are documents found by both systems.
{overlapping_documents}

## System 1 Retrieved Documents

{retrieved_documents_1}

## System 2 Retrieved Documents

{retrieved_documents_2}

## Missing Gold Documents

These are documents that are expected to be in the gold document set but were not found by either system.
{missing_gold_documents}

## Reminders

For reference, the candidate answers are presented again below:

### Candidate Answer from System 1

```
{candidate_answer_1}
```

### Candidate Answer from System 2

```
{candidate_answer_2}
```

### Original Query

```
{query}
```

## Output Format

Output only a JSON with the fields "reason", "preferred_system", and "effectively_equivalent". \
"Reason" should be a short and concise explanation for the preference classification. \
"preferred_system" must be literally "1" or "2". "effectively_equivalent" must be "true" or "false" indicating if the two answers are effectively equivalent.
You must still select 1 or 2 for "preferred_system" even if the answers are effectively equivalent.

CRITICAL: Output only a JSON object with the following fields in the order shown below:
{{
  "reason": "reason for the classification",
  "preferred_system": "1 or 2",
  "effectively_equivalent": "true or false"
}}
""".strip()
