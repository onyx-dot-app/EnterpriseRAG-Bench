# Claim-Level Gold Validation

Design note for the claim-level extension to the consensus correction flow.
Implementation: `validate_gold_claims_with_consensus` in `src/utils/eval_utils.py`,
hooked into `evaluate_single_question` in `metrics_based_eval.py`.

## Problem

The correction flow only fired on cited-vs-gold *document-set* mismatches. In a
typical 500-question run it fired on ~18 questions (3.6%) and moved the
aggregate less than 1 point. It never checked what the gold answer *says*. A
gold answer that misreads its own source documents silently penalized correct
answers, and the asymmetric penalty (a wrong detail zeroes the question) makes
each bad gold expensive.

## Mechanism

Trigger: the wholistic judge marks an answer **wrong**, correction is enabled
(no `--no-correction`), and the question has gold documents and a gold answer.

1. **Validate.** A 3-run consensus receives the question, gold answer,
   candidate answer, the judge's disagreement reason, and the **full text of
   the gold documents** (`GOLD_CLAIM_VALIDATION_PROMPT`). Each run returns
   whether the gold's disputed content and the candidate's disputed content
   are supported by the sources.
2. **Decide.** The gold is overturned only when a **majority** of usable runs
   find the gold's disputed content unsupported AND the candidate's version
   supported. Ties and failures keep the gold — the same conservative bias as
   the document flow.
3. **Repair.** On overturn: regenerate the gold answer from the gold documents
   (`update_gold_answer`), re-extract answer facts (preserving
   anti-hallucination guard facts), record
   `update_reasons.claim_validation`, and **re-score** the answer against the
   repaired gold. The updated row is written to `questions_updated.jsonl` like
   any other correction.

## What it fixes and what it does not

- Fixes: golds that misread, mistype, or paraphrase away from their source
  documents (wrong numbers, wrong identifiers, invented titles).
- Does not fix: **flaws inside the source documents themselves.** Verified
  examples: qst_0028 (the source Slack message contains both `git tag -a` and
  `git tag -s` for the same tag) and qst_0308 (the source email says "Monday
  Nov 22" where Nov 22, 2026 is a Sunday). Gold reproduces its sources
  faithfully, so source-grounded validation upholds it. Those need a
  data-generation pass on the corpus, not an eval change.
- Also caught during testing: qst_0232's gold is correct — the document's
  internal `title` field matches the gold; the candidate had quoted the
  filename slug. The earlier audit entry claiming this gold was wrong is
  retracted.

## Cost

Fires only on judged-wrong answers (~90-100 of 500). Each firing costs 3
validation calls with full gold-document text; an overturn adds one gold
regeneration, one fact extraction, and a re-score. Expected overturn rate is
low (single digits per 500) by design.

## Test evidence

- Corrupted-gold fixture (gold numbers altered away from sources, correct
  candidate): overturned with source citations; regenerated gold matches the
  sources; answer re-scored correct at 100% completeness.
- Genuine retrieval misses (candidate wrong, gold fine): upheld, no false
  overturns.
- Source-supported gold challenged by a plausible candidate (qst_0232):
  upheld with the document's title field as evidence.

## Open questions

1. **"Both unsupported" verdicts** currently keep the gold silently. Should
   they be flagged for human review instead? They may indicate a question
   whose gold documents no longer support any clean answer.
2. **Persistence.** Overturned golds land in `questions_updated.jsonl` per
   run. Should confirmed overturns be folded back into `questions.jsonl` so
   every future run benefits, and if so with what review step?
3. **Completeness interaction.** Facts are re-extracted from the repaired
   gold, so completeness for that question is measured against the new facts.
   Acceptable, or should original facts that still hold be preserved verbatim?
4. **Validator diversity.** All 3 consensus runs use the same judge model
   (`LLM_MODEL_NAME`); a shared systematic misreading survives consensus.
   Worth mixing models (e.g. `CHEAP_LLM_MODEL_NAME` as a second opinion)?
