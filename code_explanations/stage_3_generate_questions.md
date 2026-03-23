# Stage 3: Generate Questions -- Step-by-Step Overview

This document describes each of the 10 step scripts under `src/data_scripts/stage_3_generate_questions/`. All steps append questions to the shared JSONL file at `generated_data/questions.jsonl` using the `save_question()` utility, which enforces a consistent field order (`question_id`, `source_types`, `question`, `expected_doc_ids`, `gold_answer`, `answer_facts`, `question_type`).

---

## Step 1: Generate Basic Questions

**File:** `step_1_generate_basic_questions.py`

### Purpose

Generates straightforward, single-document questions by randomly sampling documents from the sources directory. Each question should be fully answerable from the content of the single selected document.

### How It Works

1. **Document selection** -- Uses `select_random_file_hierarchical()` to pick a random JSON source file. To maximize coverage, it tries up to 20 times to find a document whose UUID has not already been used in existing questions.
2. **Question generation** -- Calls `generate_question()` with the `BASIC_QUERIES_PROMPT` prompt template, passing the document title and content to the LLM.
3. **Validation** -- Calls `validate_question()` which asks the LLM to verify the question is answerable from the document and produces a gold answer.
4. **Fact extraction** -- Calls `extract_answer_facts()` to decompose the gold answer into a list of individually verifiable factual statements.
5. **Saving** -- Appends the question to `questions.jsonl` with `question_type="basic"`.

### Key Functions

- `main()` -- CLI entrypoint with `--count`, `--seed`, and `--quiet` arguments.

### LLM Usage

Three sequential LLM calls per question: generation, validation, and fact extraction.

### Inputs / Outputs

- **Input:** JSON source documents under `generated_data/sources/`.
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- Tracks `existing_uuids` in memory to avoid duplicate documents within a single run.
- Uses hierarchical random walk for balanced sampling across source type directories.
- Each question references exactly one `expected_doc_id`.

---

## Step 2: Generate Semantic Questions

**File:** `step_2_generate_semantic_questions.py`

### Purpose

Generates questions that avoid strong lexical overlap with the source document, designed to test semantic retrieval capabilities. The question should be answerable from the document but phrased so that simple keyword matching would not suffice.

### How It Works

Structurally near-identical to Step 1. The only difference is the prompt template: it uses `SEMANTIC_QUERIES_PROMPT` (from `src/prompts/basic_questions.py`) instead of `BASIC_QUERIES_PROMPT`. This prompt instructs the LLM to rephrase and paraphrase, avoiding direct terminology from the document.

### Key Functions

- `main()` -- Same CLI interface as Step 1.

### LLM Usage

Three sequential LLM calls per question (same as Step 1).

### Inputs / Outputs

- **Input:** JSON source documents under `generated_data/sources/`.
- **Output:** Appends to `generated_data/questions.jsonl` with `question_type="semantic"`.

### Notable Details

- The deduplication logic (up to 20 retries to avoid already-used document UUIDs) is the same as Step 1.

---

## Step 3: Generate Single-Document Multi-Hop Questions

**File:** `step_3_generate_single_doc_multihop_questions.py`

### Purpose

Generates questions that require synthesizing information from multiple parts of a single long document. The question should not be answerable from any single paragraph alone.

### How It Works

1. **Pre-scanning for large documents** -- Uses `collect_json_files_by_size()` to find candidate documents exceeding a minimum file size (default 3000 characters of content, with an 80% byte-to-char ratio adjustment for JSON overhead). This avoids loading every file to check content length.
2. **Document selection** -- Randomly samples from the pre-scanned candidate pool. Verifies actual content length meets `--min-doc-length` after loading, and checks the UUID has not been used already.
3. **Question generation** -- Uses the `SINGLE_DOC_MULTIHOOP_PROMPT` prompt (note: the typo "MULTIHOOP" is in the source).
4. **Validation** -- Uses a specialized answer prompt template `SINGLE_DOCUMENT_MULTIHOP_ANSWER_GENERATION` (passed via `answer_prompt_template` to `validate_question()`) that instructs the LLM to verify multi-hop reasoning is required.
5. **Fact extraction and saving** -- Same as Steps 1-2, with `question_type="single_doc_multi_hop"`.

### Key Functions

- `main()` -- CLI with additional `--min-doc-length` argument (default: 3000).

### LLM Usage

Three sequential LLM calls per question.

### Inputs / Outputs

- **Input:** JSON source documents (filtered by size).
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- The `FILE_SIZE_PROXY_RATIO = 0.8` constant accounts for JSON metadata overhead when converting the character-length minimum to a byte-level file size filter.
- References exactly one document per question, but the question requires reasoning across multiple sections of that document.

---

## Step 4: Generate Project-Related Questions

**File:** `step_4_generate_project_related_questions.py`

### Purpose

Generates cross-document questions grounded in project context. Each question may require information from multiple documents that belong to the same project. This tests multi-document retrieval and synthesis.

### How It Works

1. **Project loading** -- Loads project entries from `generation_cache/projects.json` via the `projects_cache` singleton. Each project has a description, an outline file path, and a list of document UUIDs.
2. **Project selection** -- Uses a "least-used first" strategy: `select_next_project()` picks the project with the lowest usage count (tracked in `generation_cache/project_questions.json`), breaking ties by file name.
3. **UUID resolution** -- Uses `ensure_uuids_resolved()` to build/rebuild the UUID-to-path index. Resolves each project's document UUIDs to file paths. Skips projects with fewer than 3 resolvable documents.
4. **Question generation via agent** -- Sets up a `DocumentReadTool` scoped to `SOURCES_DIR` and runs an auto-conversation (`run_auto_conversation()`) where the LLM can read project documents to formulate a cross-document question. The prompt (`PROJECT_RELATED_QUERIES_PROMPT`) provides the project overview and list of document paths.
5. **Validation** -- `validate_project_question()` presents all documents the LLM read during generation and asks the LLM to produce a gold answer plus identify which documents (by number) are relevant. Document numbers are mapped back to UUIDs.
6. **Fact extraction and saving** -- Standard `extract_answer_facts()`, then saves with `question_type="project_related"`.

### Key Functions

- `load_projects()` -- Loads projects from generation cache.
- `select_next_project()` -- Selects least-used project.
- `load_project_usage()` / `save_project_usage()` -- Manages usage counts in `generation_cache/project_questions.json`.
- `validate_project_question()` -- Custom validation that handles multi-document context and maps numbered document IDs back to UUIDs.

### LLM Usage

- One multi-turn agent conversation (up to 20 tool cycles) for question generation.
- One LLM call for validation/answer generation (with `reasoning_level="high"`).
- One LLM call for fact extraction.

### Inputs / Outputs

- **Input:** `generation_cache/projects.json`, JSON source documents, UUID index.
- **Output:** Appends to `generated_data/questions.jsonl`. Updates `generation_cache/project_questions.json`.

### Notable Details

- The `DocumentReadTool` tracks which documents the LLM reads via `doc_read_tool.read_documents`, which is used during validation.
- Source types are derived from the resolved file paths of relevant UUIDs.
- Project usage is persisted after each successful question to ensure even distribution across projects.

---

## Step 5: Generate Constrained Questions

**File:** `step_5_generate_constrained_questions.py`

### Purpose

Generates questions that use qualifiers or constraints (e.g., dates, named entities, specific conditions) to narrow the answer to a small set of documents. The LLM explores the corpus using tools to find documents and formulate a constrained question, identifying both "gold" (answer-bearing) and "distractor" (topically related but insufficient) documents.

### How It Works

1. **Source tree loading** -- Reads the pre-built source tree file (`SOURCE_TREE_PATH`) to give the LLM an overview of the corpus structure.
2. **Used document tracking** -- Maintains a cache of previously used document paths at `generation_cache/constrained_questions.json` to encourage diversity.
3. **Question generation via agent** -- Provides the LLM with five tools: `GlobTool`, `GrepTool`, `LsTool`, `DocumentReadTool`, and `FinishTool`, all scoped to `GENERATED_DATA_DIR`. The LLM explores the corpus (up to 30 tool cycles), then calls the `FinishTool` with a JSON payload containing the query, gold document paths, and distractor document paths.
4. **Approval fallback** -- If the LLM presents a proposal without calling `FinishTool`, the script sends an "Approved" message and continues for up to 5 more cycles.
5. **Error recovery** -- If the `FinishTool` output is not valid JSON, the script resets the tool and sends an error prompt asking the LLM to retry.
6. **Validation** -- `validate_constrained_question()` presents all documents (gold + distractor) numbered sequentially to the LLM, which returns a gold answer, relevant document IDs, and distractor explanations. The document IDs (1-indexed numbers) are mapped back to UUIDs.
7. **Fact enrichment** -- `extract_answer_facts()` is called, then distractor explanations from validation are appended to the answer facts list.
8. **Saving** -- Saves with `question_type="constrained"`. Updates the used document paths cache.

### Key Functions

- `generate_constrained_question()` -- Runs the agentic corpus exploration loop.
- `validate_constrained_question()` -- Validates the question and generates the gold answer against all provided documents.
- `load_documents_by_paths()` -- Loads documents from paths relative to `GENERATED_DATA_DIR`.
- `load_used_document_paths()` / `save_used_document_paths()` -- Cache management.

### LLM Usage

- One multi-turn agent conversation (up to 30 tool cycles, potentially extended with approval/error retries) for question generation.
- One LLM call for validation with `reasoning_level="high"`.
- One LLM call for fact extraction.

### Inputs / Outputs

- **Input:** Source tree file, JSON source documents, `generation_cache/constrained_questions.json`.
- **Output:** Appends to `generated_data/questions.jsonl`. Updates `generation_cache/constrained_questions.json`.

### Notable Details

- Distractor explanations are included in `answer_facts`, providing rationale for why distractor documents are not sufficient.
- Paths are relative to `GENERATED_DATA_DIR` (e.g., `sources/confluence/...`), so the `sources/` prefix is stripped when deriving source types.
- The `FinishTool` is the mechanism by which the LLM signals completion and delivers structured output.

---

## Step 6: Generate Conflicting Questions

**File:** `step_6_generate_conflicting_questions.py`

### Purpose

Generates questions about conflicting or outdated information from pairs of documents that cover overlapping topics. These pairs come from a "duplications" cache produced in an earlier pipeline stage where documents were identified as having overlapping or updated content.

### How It Works

1. **Load duplication entries** -- Reads entries from `generation_cache/duplications.json` via `duplications_cache`. Each entry has a `document_old` and `document_new` UUID.
2. **UUID resolution** -- Uses `ensure_uuids_resolved()` to build the UUID index for all referenced documents.
3. **Single-call generation** -- `process_single_entry()` loads both documents, formats them as a prompt using `CONFLICTING_INFO_PROMPT`, and makes a single LLM call. The LLM returns a JSON object with `query`, `gold_answer`, and `verifiable_statements` (used as answer facts). This is more efficient than the generate-validate-extract pipeline used by other steps.
4. **Saving** -- Both document UUIDs are listed as `expected_doc_ids`. Saved with `question_type="conflicting"`.

### Key Functions

- `process_single_entry()` -- End-to-end processing of one duplication pair. Returns `(success, message, question_data)`.
- `format_document()` -- Loads and formats a single document by UUID.
- `load_duplication_entries()` -- Reads from the duplications cache.

### LLM Usage

One LLM call per entry (with `reasoning_level="high"`). The prompt asks the LLM to produce the question, gold answer, and verifiable statements all at once.

### Inputs / Outputs

- **Input:** `generation_cache/duplications.json`, JSON source documents, UUID index.
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- **Parallelism support** -- Has a `--parallelism` argument. In parallel mode, workers run with `quiet=True`. Results are collected and saved in original entry order to keep question IDs deterministic.
- The `--count` argument limits how many duplication entries are processed (default: all).
- Both the old and new documents are always included as `expected_doc_ids` for each question.

---

## Step 7: Generate Completeness Questions

**File:** `step_7_generate_completeness_questions.py`

### Purpose

Generates questions that require information from multiple documents to answer completely. These come from a "completeness" cache produced earlier, where a question and a set of candidate document UUIDs were identified.

### How It Works

1. **Load completeness entries** -- Reads from `generation_cache/completeness.json` via `completeness_cache`. Each entry has a `question` string and a `documents` list of UUIDs.
2. **UUID resolution** -- Uses `ensure_uuids_resolved()`.
3. **Document evaluation** -- `evaluate_required_documents()` presents all candidate documents to the LLM and asks it to classify each as "required" or not for answering the question. The LLM returns a JSON object mapping each UUID to a classification. Only "required" documents are kept.
4. **Gold answer generation** -- `generate_completeness_answer()` passes the required documents and the question to the LLM, which produces a gold answer as plain text.
5. **Fact extraction** -- Standard `extract_answer_facts()`.
6. **Saving** -- The `expected_doc_ids` are the required (not all candidate) document UUIDs. Saved with `question_type="completeness"`.

### Key Functions

- `process_single_question()` -- End-to-end processing of one completeness entry.
- `evaluate_required_documents()` -- LLM-based classification of which candidate documents are actually needed.
- `generate_completeness_answer()` -- Generates the gold answer from required documents.
- `format_candidate_documents()` -- Formats documents for the evaluation prompt, returning both the text and the list of successfully loaded UUIDs.

### LLM Usage

Three LLM calls per entry (all with `reasoning_level="high"`): document evaluation, answer generation, and fact extraction.

### Inputs / Outputs

- **Input:** `generation_cache/completeness.json`, JSON source documents, UUID index.
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- **Parallelism support** -- Same pattern as Step 6. `--parallelism` flag with deterministic ordering of results.
- Requires at least 2 candidate documents per entry; skips entries with fewer.
- The document evaluation step narrows down the candidate set, so `expected_doc_ids` may be a subset of the original candidate list.

---

## Step 8: Generate Miscellaneous Questions

**File:** `step_8_generate_miscellaneous_questions.py`

### Purpose

Generates basic questions from "miscellaneous noise documents" tracked in the generation cache. These are standalone or low-connectivity documents that were produced during earlier data generation stages and recorded in `generation_cache/misc_dirs_and_files.json`.

### How It Works

1. **Load misc file UUIDs** -- Reads a flat list of document UUIDs from `misc_files_cache`.
2. **UUID resolution** -- Uses `ensure_uuids_resolved()`. Filters to resolvable UUIDs.
3. **Processing** -- `process_single_question()` loads a document by UUID, generates a question using the `BASIC_QUERIES_PROMPT` (same as Step 1), validates it, and extracts answer facts.
4. **Saving** -- Saved with `question_type="miscellaneous"`.

### Key Functions

- `process_single_question()` -- End-to-end processing of one miscellaneous document.

### LLM Usage

Three LLM calls per document (generation, validation, fact extraction), same as Steps 1-2.

### Inputs / Outputs

- **Input:** `generation_cache/misc_dirs_and_files.json`, JSON source documents, UUID index.
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- **Parallelism support** -- Same `ThreadPoolExecutor` pattern as Steps 6-7.
- Each question references exactly one document.
- The selection pool is shuffled if `--seed` or `--count` is provided, otherwise documents are processed in order from the cache.
- Defaults to processing all available documents if `--count` is not specified.

---

## Step 9: Generate High-Level Questions

**File:** `step_9_generate_high_level_questions.py`

### Purpose

Generates broad, high-level questions derived from the company overview and strategic initiatives documents. These questions are intended to require synthesizing information across multiple sources rather than being answerable from a single document.

### How It Works

1. **Load reference material** -- Reads `generated_data/company_overview.md` and `generated_data/initiatives.md`.
2. **Batch query generation** -- `generate_queries()` generates a batch of candidate queries (default: 20) in a single LLM call. The LLM returns a JSON object with numbered keys, each mapping to a query string.
3. **Validation (optional)** -- By default, validation is skipped (`--skip-validation` is `True`). When enabled, `validate_query()` gives the LLM tools (`GlobTool`, `GrepTool`, `LsTool`, `ReadTool`) scoped to `SOURCES_DIR` and up to 8 tool cycles to determine if the query is answerable from a single document. If it is, the query is rejected as "invalid" (not truly high-level). Tool calls are logged to stdout.
4. **Gold answer generation** -- `process_single_query()` passes the query and reference documents (company overview + initiatives) to the LLM with the `HIGH_LEVEL_QUESTIONS_EVALUATION_PROMPT`, producing a gold answer.
5. **Fact extraction and saving** -- Standard `extract_answer_facts()`. Saved with `question_type="high_level"`, with empty `expected_doc_ids` and `source_types` (since these questions span the entire corpus).

### Key Functions

- `generate_queries()` -- Batch generation of candidate query strings.
- `validate_query()` -- Tool-assisted validation that a query is not a single-document question.
- `process_single_query()` -- Generates gold answer and extracts facts for one query.

### LLM Usage

- One LLM call for batch candidate generation.
- (Optional) One multi-turn tool-using conversation per candidate for validation.
- One LLM call per query for gold answer generation (with `reasoning_level="high"`).
- One LLM call per query for fact extraction.

### Inputs / Outputs

- **Input:** `generated_data/company_overview.md`, `generated_data/initiatives.md`.
- **Output:** Appends to `generated_data/questions.jsonl`.

### Notable Details

- **Parallelism support** -- Same `ThreadPoolExecutor` pattern for the answer generation phase.
- `expected_doc_ids` and `source_types` are always empty lists, since these questions are not tied to specific source documents.
- The `--num-candidates` flag controls over-generation to compensate for queries that may be filtered out during validation.
- The validation tool loop has a hard cap (`MAX_VALIDATION_TOOL_CYCLES = 8`); after exceeding it, the LLM is forced to output "valid" or "invalid" with no further tool access.

---

## Step 10: Generate Unanswerable Questions

**File:** `step_10_generate_unanswerable_questions.py`

### Purpose

Generates questions that are plausible and topically related to the corpus but whose answers cannot be found in any of the available documents. These serve as negative test cases for retrieval and answer generation systems.

### How It Works

1. **Source tree** -- Builds a directory tree of `SOURCES_DIR` via `get_directory_tree()`.
2. **Used paths tracking** -- Loads previously used document paths from `unanswerable_used_paths_cache` to encourage the LLM to explore different clusters of documents each time.
3. **Question generation via agent** -- `generate_unanswerable_question()` sets up `GlobTool`, `GrepTool`, `LsTool`, and `ReadTool` scoped to `SOURCES_DIR`. The LLM explores documents (up to 20 tool cycles) to understand what is covered, then formulates a question about something that is not covered. The prompt (`CONSTRAINED_QUERIES_SYSTEM_PROMPT` from `unanswerable_question.py`) and used paths context guide the LLM.
4. **Path extraction** -- `_extract_read_paths()` parses the conversation messages to find all file paths the LLM read during exploration.
5. **Saving** -- Uses predefined constants `GOLD_ANSWER` and `GOLD_FACTS` (from the prompt module) rather than LLM-generated answers, since the correct answer is always that the question cannot be answered. Saved with `question_type="unanswerable"`, empty `expected_doc_ids` and `source_types`.

### Key Functions

- `generate_unanswerable_question()` -- Runs the agentic exploration loop.
- `_extract_read_paths()` -- Parses conversation messages for read tool call paths.
- `_load_used_paths()` / `_save_used_paths()` -- Cache management for document paths explored in previous runs.

### LLM Usage

One multi-turn agent conversation (up to 20 tool cycles) per question with `reasoning_level="high"`.

### Inputs / Outputs

- **Input:** Source documents under `generated_data/sources/`, `unanswerable_used_paths_cache`.
- **Output:** Appends to `generated_data/questions.jsonl`. Updates the used paths cache.

### Notable Details

- No validation or fact extraction LLM calls are needed since the gold answer and facts are constants.
- `expected_doc_ids` and `source_types` are always empty lists, by definition.
- The used paths cache grows across runs, progressively steering the LLM toward unexplored areas of the corpus.
- Does not support parallelism (each question depends on the updated used paths from the previous iteration).

---

## Common Patterns Across Steps

- **CLI arguments** -- All steps support `--count` and `--quiet`. Many support `--seed` for reproducibility and `--parallelism` for concurrent processing.
- **Question ID generation** -- All steps call `get_next_question_id()` to determine the next sequential ID (format: `qst_NNNN`) and increment it after each successful save.
- **Error handling** -- All steps collect errors in a list and print a summary (capped at 20 errors) at the end.
- **Appending behavior** -- All steps append to the existing `questions.jsonl` file rather than overwriting it, allowing incremental generation.
- **Parallel execution pattern** -- Steps 6, 7, 8, and 9 share a common parallel execution pattern using `ThreadPoolExecutor` with `as_completed()`. Results are sorted by original index before saving to maintain deterministic question ID assignment.
- **UUID index** -- Steps that reference documents by UUID (4, 6, 7, 8) use `ensure_uuids_resolved()` which auto-rebuilds the index if any needed UUIDs are missing.
