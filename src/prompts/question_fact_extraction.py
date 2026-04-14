FACT_EXTRACTION_PROMPT = """
Given the following question and gold answer, extract a list of individual verifiable facts from the answer. Output your response as a list of strings. \
Format it as `["fact 1", "fact 2", "fact 3", ...]`. The facts are intended to verify the completeness and accuracy of a candidate answer. \
The gold answer may contain some facts that are not necessary to fully answer the question, you should not include these in your response. \
Keep the character set of the facts simple, do not output special characters like emojis, markdown, or other non-ASCII characters.

Note: do not overly break up facts. For example, "The auth issue might be caused by a bad API key" + "The auth issue might be caused by a bad auth header" \
is better as "The auth issue might be caused by a bad API key or a bad auth header".

# Question
```
{question}
```

# Gold Answer
```
{gold_answer}
```

CRITICAL: You must output your response as a list of strings. Do not include any other text or formatting.
""".strip()


ANTI_HALLUCINATION_FACT_VALIDATOR_PROMPT = """
You are given a list of facts which must be part of an expected answer. Some of them may be negation type statements which is to prevent hallucinations. \
If those exist in the list, you must output them in a list verbatim as they are in the fact list below. If there are no such anti-hallucination statements, you must output an empty list.

Fact List:
```
{fact_list}
```

Your output should be a list of strings like `["answer must not contain X", "the answer should not be Y", ...]`.
""".strip()
