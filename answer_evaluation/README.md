Place your answer file in this directory (defaults to looking for a file called answers.jsonl) and run src/answer_evaluation.py. Note you'll have to set up your LLM keys.

The per-question entries in `answer_evaluation/results.json` include:
- `question_type`: copied from the source question row.
- `gold_answer_updated`: `true` when evaluation changed the stored gold answer before scoring.

`answer_evaluation/results.json` is updated incrementally while the run is in progress. Each completed question is appended under `questions`, and the file writes are serialized through the main process even when evaluation uses `--parallelism > 1`.
