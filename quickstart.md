# Quickstart

This guide covers two paths:
1. **Evaluate your system** — download the dataset, run your RAG pipeline, and score the results.
2. **Generate your own dataset** — create a custom corpus for a different industry, company size, or source mix.

## Prerequisites

Python 3.10+

```bash
pip install -r requirements.txt
```

### Environment Variables

An LLM is required for both evaluation and data generation. Set up the following before running any scripts:

```bash
# Required: LLM provider ("openai" or "anthropic", defaults to "openai")
export LLM_PROVIDER="openai"

# Required: API key for your chosen provider
export LLM_API_KEY="your-api-key-here"

# Optional: Override the default model (defaults: "gpt-5.4" for OpenAI, "claude-sonnet-4-6" for Anthropic)
export LLM_MODEL_NAME="gpt-5.4"

# Optional: Override the cheap model used for less critical operations (defaults: "gpt-5-mini" for OpenAI, "claude-haiku-4-5" for Anthropic)
export CHEAP_LLM_MODEL_NAME="gpt-5-mini"
```

---

## Evaluate Your System

### 1. Download the data

Grab the dataset from the [latest release](../../releases/latest) or [HuggingFace](https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench):
- **`all_documents.zip`** — all documents in a single archive with directory structure preserved.
- **`<source_type>_slice_<slice_number>.zip`** — per-source-type zips of up to 5,000 flat files each.

### 2. Understand the document format

Exported documents are `.txt` files. Each file name is prefixed with a dataset UUID (`dsid_<sha>`) followed by a semantic name.
The file contents start with the document title, followed by all content fields. The directory structure mirrors the source types (Slack, Gmail, Google Drive, etc.).

### 3. Understand the question set

The benchmark ships with [questions.jsonl](questions.jsonl) containing 500 questions across 10 categories:

| # | Category | Count | Description |
|---|----------|-------|-------------|
| 1 | Basic | 200 | Simple questions with a single ground truth document. |
| 2 | Semantic | 100 | Similar to Basic but more roundabout, with less keyword/phrase overlap and without giveaway-type keywords. |
| 3 | Intra-Document Reasoning | 50 | Requires combining information from several distant sections of a single longer document. |
| 4 | Project Related | 40 | Aggregate knowledge from related documents from a single project/initiative within the company. |
| 5 | Constrained | 30 | Questions with multiple relevant documents but with qualifiers that disqualify all but one answer. |
| 6 | Conflicting Info | 20 | Questions where documents directly contradict each other. Requires the system to give a complete and correct answer. |
| 7 | Completeness | 10 | Questions that require fetching all relevant documents (no more than 10) to be able to provide a correct answer. |
| 8 | Miscellaneous | 20 | Questions targeting informal, off-topic, or loosely organized documents (e.g. `slack/memes`, `github/hackathons`). |
| 9 | High Level | 10 | High level questions where the answer is not located in any single document. Note: these do not have any ground truth documents. |
| 10 | Info Not Found | 20 | Questions where the answer is not available. Note: these do not have any ground truth documents. |

An additional 100 metadata-dependent questions are available in [extra_questions.jsonl](extra_questions.jsonl) for teams interested in metadata-aware RAG.
These are excluded from the leaderboard since their evaluation criteria differ from the core retrieval-focused benchmark.

### 4. Format your answers

Create a JSONL file where each line contains:

```json
{"question_id": "qst_0001", "answer": "Your answer text...", "document_ids": ["dsid_abc", "dsid_def"]}
```

Each row needs at least one of `answer` or `document_ids`. Both are needed for a complete evaluation (correctness/completeness require `answer`, document recall requires `document_ids`).

### 5. Run metrics-based evaluation

Scores a single system on four metrics:

| Metric | Description |
|--------|-------------|
| **Correctness** | Holistic LLM judgment of whether the answer aligns with the gold answer. |
| **Completeness** | Percentage of `answer_facts` supported by the candidate answer. |
| **Document Recall** | Percentage of gold documents present in the candidate's retrieved set. |
| **Invalid Extra Documents** | Count of candidate documents that are neither in the gold set nor classified as relevant by the evaluation. |

```bash
python -m src.scripts.answer_evaluation.metrics_based_eval \
    --answers-file answer_evaluation/answers.jsonl
```

Results are written to `answer_evaluation/results.json`.

### 6. Run comparative evaluation (optional)

Compares two systems head-to-head with three-judge consensus voting:

```bash
python -m src.scripts.answer_evaluation.comparative_eval \
    --answer-file-1 answer_evaluation/system_1.jsonl \
    --answer-file-2 answer_evaluation/system_2.jsonl
```

Results are written to `answer_evaluation/results-comparative.json`.

### Evaluation tips

- **Parallelism**: Use `--parallelism N` to speed things up.
- **Resume**: Both scripts support `--resume` to skip already-evaluated questions. Use `--question-id qst_XXX` to re-evaluate a single question.
- **Gold-answer corrections**: When your candidate documents differ from the gold set, the evaluation runs a three-judge consensus to decide whether the gold set should be updated.
Corrected questions are written to a separate `questions_updated` file and flagged in the results. See the [Correction Utilities](methodology.md#correction-utilities) section for details.

---

## Repo Layout

| Directory / File | Purpose |
|------------------|---------|
| `questions.jsonl` | The 500 benchmark questions. |
| `extra_questions.jsonl` | 100 additional metadata-dependent questions (not part of the leaderboard). |
| `export_data/` | Final exported zip files of the dataset. |
| `generated_data/` | Raw JSON documents with rich metadata. |
| `generated_data/sources/` | The corpus organized by source type (Slack, Gmail, etc.). |
| `generation_cache/` | Intermediate state shared between generation steps. |
| `src/scripts/` | All runnable scripts, organized by stage. |
| `answer_evaluation/` | Convenience directory for placing answer files and viewing results. |
| `methodology.md` | Detailed explanation of the generation process, evaluation, and known limitations. |

### Export data format

The `export_data/` directory contains the final zip files for the generated dataset. Documents are represented as `.txt` files inside the zips.
File names are prefixed with the dataset UUID (`dsid_`), followed by a SHA, followed by the semantic file name.
The file contents start with the document title, followed by all content fields identified by the LLM.

Two export formats are provided:
- **`all_documents.zip`** — preserves the full directory structure. Top level contains source types, each with nested subdirectories.
- **`<source_type>_slice_NNNN.zip`** — flat zips broken down by source type, up to 5,000 documents each. Useful for working with subsets of the data.

---

## Generate Your Own Dataset

This section is for teams that want to create a custom corpus — a different industry, company size, source mix, or document volume.

### Clean slate

Delete the existing generated data before starting:

```bash
rm -rf export_data generated_data generation_cache
```

### Overview

Generation is split into four stages:

1. **Stage 1 — Generate clean data** (steps 1–9): Build the company context, scaffolding, and documents.
2. **Stage 2 — Add noise** (steps 1–4): Introduce shuffling, miscellaneous files, and near-duplicates.
3. **Stage 3 — Generate questions** (steps 1–10): Create the question set, one step per question type.
4. **Stage 4 — Export** : Package the dataset into distributable zip files.

Steps are run in order. Some steps in Stage 1 and Stage 2 are **interactive** (human-in-the-loop), meaning you'll collaborate with the LLM to shape the dataset. These are marked below.

> **Cost note**: Steps 7 (project documents) and 9 (volume documents) account for the bulk of LLM cost since they generate the actual document corpus. The scaffolding and question generation steps are comparatively cheap. Parallelism flags on these steps control both speed and peak API usage.

A [`.vscode/launch.json`](.vscode/launch.json) is provided with debug configurations for every step if you use VS Code or VS Code-based editors (Cursor, Windsurf, etc.).

### Stage 1 — Generate clean data

#### Steps 1–5: Scaffolding (interactive)

These steps build the foundation that guides all downstream generation. It's worth spending time here — they shape the company identity, org structure, source layout, and document format conventions.

**Step 1 — Generate company overview** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_1_generate_company_overview
```

**Step 2 — Generate initiatives** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_2_generate_initiatives
```

**Step 3 — Generate employee directory** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_3_generate_employee_directory
```

**Step 4 — Generate source structure** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_4_generate_source_structure
```

**Step 5 — Generate agents.md files** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_5_generate_agents_md
```

#### Steps 6–8: Core high-fidelity documents

These steps generate tightly connected, project-aware documents. Each document is informed by the company context, project scaffolding, and sibling documents.

**Step 6 — Generate projects**
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_6_generate_projects \
    --max-parallelization 5 \
    --dedup-parallelism 20
```

**Step 7 — Generate project documents**
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_7_generate_project_documents \
    --project-parallelism 5 \
    --project-file-parallelism 5 \
    --labeling-parallelism 20
```

**Step 8 — Generate completeness documents** (interactive)
```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_8_generate_completeness_documents \
    --count 10
```

#### Step 9: High-volume documents

Generates the bulk of the corpus. Uses topic scaffolding to prevent LLM drift and clustering. Lower fidelity than project documents but significantly cheaper.

```bash
python -m src.scripts.data_gen_stage_1_generate_clean_data.step_9_generate_volume_documents \
    --source-parallelism 5 \
    --topic-parallelism 5 \
    --doc-parallelism 10
```

### Stage 2 — Add noise

**Step 1 — Random shuffle**
```bash
python -m src.scripts.data_gen_stage_2_add_noise.step_1_random_shuffle \
    --percentage 3.0
```

**Step 2 — LLM-based shuffle**
```bash
python -m src.scripts.data_gen_stage_2_add_noise.step_2_llm_based_shuffle \
    --percentage 3.0 \
    --parallelism 50
```

**Step 3 — Generate miscellaneous files** (interactive)
```bash
python -m src.scripts.data_gen_stage_2_add_noise.step_3_generate_misc_files \
    --count 20 \
    --parallelism 5
```

**Step 4 — Generate near-duplicate files**
```bash
python -m src.scripts.data_gen_stage_2_add_noise.step_4_generate_near_duplicates \
    --count 20
```

### Stage 3 — Generate questions

Each step corresponds to one of the 10 question types. Common flags across all steps:
- `--count N` — number of questions to generate.
- `--quiet` — suppress LLM output streaming.
- `--parallelism N` — parallel workers (available on some steps).

> **Dependencies**: Step 6 (Conflicting) requires near-duplicates from Stage 2 Step 4. Step 7 (Completeness) requires completeness clusters from Stage 1 Step 8. Step 8 (Miscellaneous) requires misc files from Stage 2 Step 3.

**Step 1 — Basic questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_1_generate_basic_questions \
    --count 50
```

**Step 2 — Semantic questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_2_generate_semantic_questions \
    --count 50
```

**Step 3 — Intra-document reasoning questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_3_generate_intra_doc_reasoning_questions \
    --count 50 \
    --min-doc-length 3000
```

**Step 4 — Project-related questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_4_generate_project_related_questions \
    --count 50
```

**Step 5 — Constrained questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_5_generate_constrained_questions \
    --count 50
```

**Step 6 — Conflicting info questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_6_generate_conflicting_questions \
    --count 20 \
    --parallelism 1
```

**Step 7 — Completeness questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_7_generate_completeness_questions \
    --count 10 \
    --parallelism 1
```

**Step 8 — Miscellaneous questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_8_generate_miscellaneous_questions \
    --count 20 \
    --parallelism 1
```

**Step 9 — High-level questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_9_generate_high_level_questions \
    --count 10 \
    --num-candidates 20 \
    --parallelism 1
```

**Step 10 — Info Not Found questions**
```bash
python -m src.scripts.data_gen_stage_3_generate_questions.step_10_generate_info_not_found_questions \
    --count 20
```

### Stage 4 — Export

The export script packages `generated_data/sources/` into distributable zip files with configurable format options:

```bash
python -m src.scripts.data_gen_stage_4_data_export.export_data \
    --max-files 100 \           # Max total files to export (optional)
    --random-sample \           # Randomly sample files, only applies with --max-files (optional)
    --flatten-within-sources \  # Flatten files within each source directory (optional)
    --sources slack gmail \     # Source types to include (default: all)
    --create-zip \              # Create zip file(s) (optional)
    --max-files-per-zip 5000 \  # Max files per zip, creates incremental slices when exceeded (optional)
    --split-by-source \         # Separate zip per source type (optional)
    --export-format txt         # "txt" for plain text or "json" for original format with metadata (default: txt)
```

Two common export patterns:

```bash
# Single zip with full directory structure
python -m src.scripts.data_gen_stage_4_data_export.export_data --create-zip

# Per-source flat zips of up to 5,000 files each
python -m src.scripts.data_gen_stage_4_data_export.export_data --create-zip --split-by-source --max-files-per-zip 5000 --flatten-within-sources
```

---

## Answer Generation (Optional)

The repository includes three retrieval approaches for generating candidate answers. These are primarily useful for **refining the gold question set** through the evaluation correction flow — by pooling results from structurally different retrievers, incomplete or incorrect gold answers are more likely to be surfaced and corrected.

See the [Answer Generation README](src/scripts/answer_generation/README.md) for usage and architecture details.

### BM25 keyword search baseline

A traditional keyword-based retrieval pipeline using OpenSearch. Documents are indexed with title and content in a single text field. No embeddings required — queries use standard BM25 scoring. The cheapest and fastest option, best when queries and documents share significant keyword overlap.

### Vector search baseline

A straightforward embed-and-retrieve pipeline using OpenAI embeddings and Qdrant. Fast and cheap, works well when query and document share strong semantic overlap.

### Agent-based retrieval

An LLM agent that explores the corpus iteratively using shell commands (`grep`, `find`, `jq`, etc.). Significantly more expensive and slower, but handles complex multi-hop queries and questions where directory structure matters.

### Alternative: coding agents

The agent-based approach can also be approximated using coding agents like Claude Code or Opencode with an AGENTS.md file pointed at the corpus. An example AGENTS.md is provided in [agents_example.md](src/scripts/answer_generation/agents_example.md).

---

## Leaderboard Submission

To submit results for the EnterpriseRAG Benchmark leaderboard, reach out to joachim@onyx.app. Submissions must provide a method of verification:
- **Open source**: A guide for reproducing results.
- **Closed source**: A sandbox or URL where questions can be sent for verification.
