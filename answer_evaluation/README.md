# Answer Evaluation

This directory is provided for your convenience, the scripts for answer evaluation look for certain files in this directory as a default.

For more details on the process and evaluation methods, see [methodology.md](methodology.md#evaluation)

## Answer File Format

Place your answers in a JSONL file. Each line:

```json
{"question_id": "qst_001", "answer": "Your answer text...", "document_ids": ["dsid_abc", "dsid_def"]}
```

Each row needs at least one of `answer` or `document_ids`, both are needed for a complete evaluation.

## Metrics-Based Evaluation

Scores a single system on correctness, completeness, document recall, and invalid extra documents.

```bash
python -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file answer_evaluation/answers.jsonl
```

Results are written to `answer_evaluation/results.json` by default.

## Comparative Evaluation

Compares two systems head-to-head with three-judge consensus voting.

```bash
python -m src.scripts.answer_evaluation.comparative_eval \
    --answer-file-1 answer_evaluation/system_1.jsonl \
    --answer-file-2 answer_evaluation/system_2.jsonl
```

Results are written to `answer_evaluation/results-comparative.json` by default.

## Notes

- Both scripts auto-resume from existing results files. Use `--question-id qst_XXX` to re-evaluate a single question.
- Use `--parallelism N` to run evaluations in parallel.
- Questions that receive corrections are flagged in the results and written to a separate `questions_updated` file.
- Run the scripts with `--help` for all options.
- You will need to export the necessary env variables for the LLM of choice to run the evals.
