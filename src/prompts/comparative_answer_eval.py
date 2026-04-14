IS_GOLD_DOCUMENT_STR = " (gold document, this is one of the document set's expected documents for this question.)"

DOCUMENT_TEMPLATE = """
### Document {number}{is_gold_document_str}

```
{document_title}
{document_contents}
```
"""

COMPARATIVE_EVAL_PROMPT = """
You are an answer comparison expert. Given a query, sets of backing documents, and two candidate answers, evaluate which answer is better and provide justification. \
The two answers come from two different search systems and both provide their source documents. For documents which are retrieved by both systems, they are listed in the "Overlapping Documents" section. \
Some documents may be marked as gold documents but this does not guarantee them to be the best documents for the query or sufficient on their own for a complete answer. \
It is possible for other documents to even supersede and invalidate the gold documents. Sometimes neither system will retrieve the gold document so you may not see the label anywhere. \
Your task is to evaluate the answers and determine if one system's answer is preferred over the other and if they are close to equivalent. \
The two systems are considered equivalent if the answer contains very similar amounts of clearly useful information. \
Discount but do not penalize information which is helpful but only peripherally related to the query or not directly relevant to the question. \
Related information that might be helpful (but is not directly relevant to the question) should be considered positive however related information which may be misleading should be considered negative. \
If an answer contains provably incorrect information based on the documents, it should be strongly penalized. Do not favor systems for being more or less "helpful" (ignore things like offering follow ups etc.).

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
