# Poisoned-Document Split — Proposal

## Motivation

EnterpriseRAG-Bench already tests realistic *noise*: misfiled documents, outdated versions, near-duplicates with conflicting facts. But there is a category of enterprise corruption the current categories don't isolate: **deliberately manipulated documents** — tampered figures, edited dates, forged approvals — and **synthetic documents** (AI-generated filler designed to look like legitimate internal docs).

This matters because real enterprises increasingly face both:

- **Document fraud**: edited invoices, altered contracts, modified expense reports entering the corpus from users, vendors, or compromised accounts.
- **AI slop ingestion**: LLM-generated documents (fake policies, synthetic meeting notes, generated "evidence") entering via user uploads or over-eager automation.

A RAG system that retrieves a tampered document will answer *confidently* from it — grounding is only as good as the corpus. The existing "Conflicting Info" category tests contradictions between legitimate docs; this split tests **trust in a single corrupted source**.

## Proposed split: `poisoned_source`

**Question type:** `poisoned_source` (~30 questions)

Each question targets a document that has been deliberately corrupted in one of two ways:

1. **Tampered**: a legitimate document with altered key facts — changed amounts, dates, approval names, version numbers. The gold answer reflects the *original* ground truth; a system that retrieves and trusts the tampered version produces a confident wrong answer. Evaluated on whether the system detects/flags the inconsistency rather than parroting the tampered value.

2. **Synthetic**: an LLM-generated document styled like a real internal doc (fake policy, fake incident report) with no legitimate counterpart. Evaluated on whether the system either refuses to ground on it, flags it as suspicious, or correctly reports "info not found" per the existing `info_not_found` convention.

## Design sketch

For each poisoned document:

- Keep the **untampered sibling** in the corpus (as with existing near-duplicate noise), so retrieval sees both and must adjudicate.
- Tamper operations applied to the corrupted copy: numeric substitution (amounts, limits, percentages), date shifts, entity swaps (names/owners), status flips (approved/rejected).
- Synthetic docs are generated with the same scaffolding as legitimate docs (same tone, formatting, codenames) but reference nonexistent projects/people — detectable only by cross-referencing the employee directory or project registries, or by provenance signals.
- Each question records: `poison_type` (`tampered` | `synthetic`), `tamper_ops` (list), `expected_doc_ids` (the poisoned doc), and `gold_answer` reflecting the true state.

## Scoring

Two complementary metrics:

1. **Robustness**: fraction of poisoned-source questions where the system does NOT assert the tampered/synthetic value as fact.
2. **Detection**: fraction where the system explicitly flags uncertainty, cites the conflicting clean sibling, or reports info-not-found.

Both require answer evaluation that goes beyond token overlap — the existing `answer_evaluation` LLM-judge flow is a good fit, with a rubric addition for "asserted corrupted value" vs "flagged or abstained".

## Optional provenance signal

Systems can optionally enrich documents with provenance metadata before ingestion. As a working example, [Stipple](https://github.com/Sketchjar/stipple-mcp) (hosted document-forensics API, free anonymous tier) returns a `risk_band` + per-signal evidence for tampered PDFs/images and an AI-written-prose probability for synthetic text — a pre-ingestion trust gate could flag poisoned docs before they're indexed. This is exactly the kind of metadata-aware signal `extra_questions.jsonl` already anticipates. (Disclosure: this proposal comes with such an integration shipped — see [stipple-kits](https://github.com/Sketchjar/stipple-kits) — but the split itself is tool-agnostic: the tamper/synthetic operations are self-contained and any detection method can be scored against them.)

## Generation path

The repo's generation framework (`src/scripts/data_gen_stage_*`) already supports noise injection (`data_gen_stage_2_add_noise`). The poisoned split fits as a `data_gen_stage_2b_add_poison` stage:

1. Sample high-fidelity docs with clear extractable facts.
2. Apply scripted tamper ops (deterministic, auditable) or generate synthetic siblings.
3. Emit questions with `poison_type` + tamper audit trail.

Happy to contribute the stage implementation and an initial question batch if maintainers are interested.
