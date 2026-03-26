# Evaluation Process

This directory is provided for your convenience to run evaluation on your candidate answers/documents. There are two options for evaluation:
- A metrics based evaluation which evaluates every answer independently against the gold documents/answers.
- A comparitive evaluation which takes 2 separate answer files and runs a head to head between them for every question.

## Metrics Based Evaluation
```
command to run
```

## Comparitive Evaluation

## Answer Updating

Place your answer file in this directory (defaults to looking for a file called answers.jsonl) and run src/answer_evaluation.py. Note you'll have to set up your LLM keys.

The per-question entries in `answer_evaluation/results.json` include:
- `question_type`: copied from the source question row.
- `gold_answer_updated`: `true` when evaluation changed the stored gold answer before scoring.

`answer_evaluation/results.json` is updated incrementally while the run is in progress. Each completed question is appended under `questions`, and the file writes are serialized through the main process even when evaluation uses `--parallelism > 1`.
