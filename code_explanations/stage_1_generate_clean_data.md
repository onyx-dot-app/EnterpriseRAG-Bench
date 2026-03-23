# Stage 1: Generate Clean Data -- Step-by-Step Code Overview

This document provides a detailed overview of each step script (1 through 9) in
`src/data_scripts/stage_1_generate_clean_data/`. These scripts form a sequential pipeline
that builds a synthetic enterprise dataset from scratch: starting with high-level company
context and ending with thousands of individual source documents.

---

## Step 1: Generate Company Overview

**File:** `step_1_generate_company_overview.py`

### Purpose

Generates a foundational company overview document (`generated_data/company_overview.md`)
that serves as the shared context for every subsequent generation step. This is the very
first artifact in the pipeline and defines the fictional company's identity, domain,
products, and organizational structure at a high level.

### How It Works

1. Checks if `company_overview.md` already exists. If so, prompts the user with
   `confirm_regenerate()` and either updates statistics or proceeds.
2. Creates a `WriteTool` with a fixed file path override pointing to
   `COMPANY_OVERVIEW_PATH`.
3. Initializes an LLM via `get_llm()` with the write tool's schema attached.
4. Launches an interactive `Conversation` loop between the user and the LLM. The LLM
   is seeded with `COMPANY_OVERVIEW_SYSTEM_PROMPT` and the user guides the conversation
   until the LLM writes the company overview to disk using the write tool.
5. After the conversation ends, records completion in aggregate statistics.

### Key Functions

- `main()` -- Orchestrates the entire flow.

### LLM Usage

- A single LLM instance with a write tool. The user interacts with it in a free-form
  conversation loop (`run_interactive_loop`). The LLM decides when to call the write
  tool to persist the document.

### Inputs / Outputs

- **Input:** User guidance via interactive prompts.
- **Output:** `generated_data/company_overview.md`

### Notable Details

- The `WriteTool` is configured with `file_path_override`, meaning the LLM cannot
  choose the output path -- it always writes to the predetermined location.
- This is a fully interactive (human-in-the-loop) step.

---

## Step 2: Generate Initiatives

**File:** `step_2_generate_initiatives.py`

### Purpose

Generates a company initiatives and roadmap document (`generated_data/initiatives.md`)
that describes the fictional company's strategic priorities, projects in flight, and
planned work. These initiatives inform the topics and content of documents generated
in later steps.

### How It Works

1. Checks if `initiatives.md` already exists and offers to skip.
2. Loads the previously generated `company_overview.md` and injects it -- along with
   the current date -- into `INITIATIVES_SYSTEM_PROMPT`.
3. Creates a `WriteTool` with a fixed path override to `INITIATIVES_PATH`.
4. Runs an interactive conversation loop where the LLM, seeded with company context,
   collaborates with the user to produce the initiatives document.
5. Updates statistics on completion.

### Key Functions

- `main()` -- Orchestrates the flow.

### LLM Usage

- Single LLM instance with a write tool. Interactive conversation loop identical in
  structure to Step 1.

### Inputs / Outputs

- **Input:** `generated_data/company_overview.md`, user guidance.
- **Output:** `generated_data/initiatives.md`

### Notable Details

- The system prompt is formatted with the full company overview content and the current
  date, giving the LLM full context about the company when generating initiatives.

---

## Step 3: Generate Employee Directory

**File:** `step_3_generate_employee_directory.py`

### Purpose

Generates a YAML-based employee directory (`generated_data/employee_directory.yaml`)
containing departments, employees, titles, emails, and reporting relationships.
Employees defined here are referenced as authors and participants in generated documents
throughout the rest of the pipeline.

### How It Works

1. Checks if the employee directory exists and offers to skip.
2. Loads `company_overview.md` and `initiatives.md` as context.
3. Creates a `WriteTool` with path override to `EMPLOYEE_DIRECTORY_PATH` and attaches
   a **schema validator** (`validate_employee_directory`) so that the LLM's output is
   validated against the `EmployeeDirectory` Pydantic model on every write attempt.
4. Also creates a `FinishTool` so the LLM can signal when it considers the directory
   complete.
5. Runs an interactive conversation. When the LLM calls the finish tool, the script
   triggers a comprehensive validation phase before accepting the result.

### Key Functions

- `load_employee_directory()` -- Parses the YAML file into an `EmployeeDirectory` model.
- `check_duplicate_emails()` -- Ensures no two employees share an email address.
- `check_manager_validity()` -- Verifies every referenced manager exists in the directory.
- `check_cycles()` -- Detects cycles in the reporting chain (e.g., A reports to B
  reports to A).
- `generate_org_chart()` / `write_tree()` -- Builds a visual ASCII org chart from the
  directory data.
- `run_validation()` -- Runs all validations and, on success, writes the org chart to
  `VISUAL_EMPLOYEE_DIRECTORY_PATH`.
- `on_finish()` -- Callback invoked when the LLM signals completion. Runs validation;
  if validation fails, resets the finish tool and continues the conversation so the
  user/LLM can fix issues.

### LLM Usage

- Single LLM with write and finish tools. Interactive conversation with a validation
  gate at the end.

### Inputs / Outputs

- **Input:** `company_overview.md`, `initiatives.md`, user guidance.
- **Output:** `generated_data/employee_directory.yaml`, visual org chart file.

### Notable Details

- The `WriteTool` is configured with both a `validator` and an `expected_format`,
  giving the LLM feedback if its YAML output does not conform to the schema.
- Validation is thorough: structural (Pydantic), duplicate emails, manager existence,
  and cycle detection.
- If validation fails after the LLM signals finish, the finish tool is reset and the
  conversation continues rather than aborting.

---

## Step 4: Generate Source Structure

**File:** `step_4_generate_source_structure.py`

### Purpose

Creates the directory tree under `generated_data/sources/` that represents the various
data source types (e.g., `slack/`, `confluence/`, `github/`, `google_drive/`) and their
subdirectories (channels, spaces, repos, etc.). This structure is the skeleton that
later steps populate with documents.

### How It Works

1. Checks if source directories already exist and offers to skip.
2. Loads `company_overview.md` and `initiatives.md` as context.
3. Creates a tool set for directory manipulation: `MkdirTool`, `RmdirTool`, `MvdirTool`,
   `TreeTool`, `ReadEmployeeDirectoryTool`, and `FinishTool` -- all scoped to
   `SOURCES_DIR` as their base directory.
4. Runs an interactive conversation where the LLM creates, renames, and organizes
   directories using these tools.
5. On finish, writes the directory tree to `source_tree.txt` and updates statistics.

### Key Functions

- `count_directories()` -- Counts top-level and total nested directories.
- `write_source_tree()` -- Serializes the directory tree to `SOURCE_TREE_PATH`.
- `on_finish()` -- Writes the source tree and records statistics.

### LLM Usage

- Single LLM with directory manipulation tools. Interactive conversation.
- A separate LLM instance is used internally by `ReadEmployeeDirectoryTool` for
  filtering employee directory queries.

### Inputs / Outputs

- **Input:** `company_overview.md`, `initiatives.md`, user guidance.
- **Output:** Directory tree under `generated_data/sources/`, `source_tree.txt`.

### Notable Details

- The script suggests running in batches (one source type at a time) to avoid long,
  expensive conversations.
- All directory tools are scoped to `SOURCES_DIR` to prevent operations outside the
  intended area.

---

## Step 5: Generate Agents MD

**File:** `step_5_generate_agents_md.py`

### Purpose

Creates `agents.md` files in source directories. These files act as configuration and
instruction documents that guide subsequent document generation steps. They define
content rules, metadata expectations, naming conventions, and target document counts
for each source type or subdirectory.

### How It Works

1. Checks if any `agents.md` files already exist; if so, asks whether to generate more.
2. Loads `company_overview.md` and `source_tree.txt` as context.
3. Creates a `WriteTool` scoped to `SOURCES_DIR` with `allow_create_dirs=False`
   (can only write files, not create new directories) and a `FinishTool`.
4. Runs an interactive conversation where the LLM writes `agents.md` files into the
   appropriate source directories.
5. On finish, records paths and count of generated `agents.md` files in statistics.

### Key Functions

- `find_agents_md_files()` -- Recursively finds all `agents.md` files under a base
  directory.
- `on_finish()` -- Records statistics about created files.

### LLM Usage

- Single LLM with write and finish tools. Interactive conversation.

### Inputs / Outputs

- **Input:** `company_overview.md`, `source_tree.txt`, user guidance.
- **Output:** `agents.md` files in various directories under `generated_data/sources/`.

### Notable Details

- The script explicitly encourages manual post-editing of generated `agents.md` files.
- `allow_create_dirs=False` ensures the LLM writes into the existing directory structure
  from Step 4 without accidentally creating new directories.
- The top-level `agents.md` for each source type is described as the most important;
  subdirectory-level files are optional.

---

## Step 6: Generate Projects

**File:** `step_6_generate_projects.py`

### Purpose

Generates project definitions -- concrete, team-scoped work items (smaller in scope than
initiatives). Each project is enriched with a description, a list of associated source
file paths and descriptions, and a list of people involved. Output is a set of JSON
files under `generated_data/projects/`.

### How It Works

This is the most complex step, operating in four sequential phases:

**Phase 1 -- Interactive Project List Generation:**
Runs an interactive conversation where the user and LLM collaboratively produce a plain-text
list of projects written to `PROJECT_LIST_PATH`. The format is sections with `# Header`
lines and `project_name: description` entries. If the file already exists, this phase
is skipped.

**Phase 2 -- Enrich Projects (Parallel):**
Parses the project list into `(name, description)` tuples. For each project, runs an
automated LLM conversation (`run_auto_conversation`) that uses `TreeTool`, `GlobTool`,
`ReadTool`, and `ReadEmployeeDirectoryTool` to explore the source directory structure
and produce a JSON object with a full description and a list of file paths with
descriptions. Validation uses the `ProjectEnrichment` schema. Invalid file paths are
filtered out. Processes projects in parallel using `ThreadPoolExecutor`.

**Phase 3 -- Deduplicate File Paths (Parallel):**
Detects file path conflicts (the same path assigned to multiple projects). For each
conflict, the LLM proposes a new unique file path and description. Uses thread-safe
locks (`paths_lock` for the global path set, per-project locks for file writes) to
handle concurrent deduplication. Falls back to manual user input if the LLM fails
after multiple attempts.

**Phase 4 -- Populate People (Parallel):**
For projects missing a `people` field, uses the LLM to assign relevant employees from
the employee directory to each project. Validates against the `ProjectPeople` schema
and filters invalid entries.

### Key Functions

- `parse_project_list()` -- Parses the `# Section / name: description` format into
  structured tuples.
- `project_name_to_filename()` -- Sanitizes project names into safe filenames.
- `enrich_single_project()` -- Runs an automated LLM conversation to produce enriched
  project JSON with validation and one retry.
- `process_single_project()` -- Wrapper for parallel enrichment.
- `find_file_conflicts()` / `find_similar_files()` -- Detect path collisions and
  near-duplicate filenames.
- `propose_dedup()` -- LLM-based deduplication proposal with retry history.
- `try_resolve_conflict()` -- Thread-safe conflict resolution with atomic path
  reservation.
- `apply_manual_dedup()` -- Fallback for user-driven conflict resolution.
- `add_people_to_project()` -- LLM-based people assignment with validation.

### LLM Usage

- Phase 1: Interactive conversation with write tool.
- Phase 2: Automated conversations (`run_auto_conversation`) with exploration tools,
  run in parallel.
- Phase 3: Simple LLM calls (no tools) for deduplication proposals, run in parallel.
- Phase 4: Simple LLM calls for people assignment, run in parallel.

### Inputs / Outputs

- **Input:** `company_overview.md`, `initiatives.md`, `source_tree.txt`,
  `employee_directory.yaml`, source directory structure.
- **Output:** JSON files in `generated_data/projects/`, one per project.

### Notable Details

- Deduplication uses thread-safe locking with per-project and global-path locks to
  prevent race conditions during parallel resolution.
- The deduplication LLM gets previous failed attempts replayed in the conversation to
  avoid repeating rejected paths.
- People population was split into a separate phase because combining it with
  enrichment had too high a miss rate.
- Supports `--max-parallelization` and `--dedup-parallelism` CLI arguments.

---

## Step 7: Generate Project Documents

**File:** `step_7_generate_project_documents.py`

### Purpose

Generates the actual source document JSON files for every file path listed in the
enriched project definitions from Step 6. Also labels each document with field metadata
and assigns unique dataset UUIDs. Finally, writes a project-to-document mapping cache
for use in question generation.

### How It Works

Operates in four phases:

**Phase 1 -- Generate Documents (Parallel):**
Iterates over every project JSON file and, for each listed file path, runs an automated
LLM conversation to generate the document content. The LLM receives the company overview,
the full project JSON for context, and all `agents.md` files found along the target
file's directory path. The generated JSON is validated for correct structure (no nested
dicts) and written to the appropriate location under `generated_data/sources/`. Supports
two levels of parallelism: across projects and within each project's files.

**Phase 2 -- Label Document Fields (Parallel):**
Finds all documents missing `title_field_name` and `content_field_names` labels. Uses
`label_single_document()` (which calls the LLM) to identify which JSON fields represent
the document's title and content.

**Phase 3 -- Add Dataset UUIDs (Parallel):**
Scans all JSON documents and adds a `dataset_doc_uuid` field to any that lack one.
Uses `add_dataset_doc_uuid()` which generates a deterministic or random UUID.

**Phase 4 -- Write Question Cache:**
Builds `generation_cache/projects.json` by reading each project file, collecting the
`dataset_doc_uuid` values from its associated documents, and writing entries with the
project filename, description, and list of document UUIDs.

### Key Functions

- `get_agents_md_along_path()` -- Walks from `sources/` down to the file's parent
  directory, collecting all `agents.md` content along the way. Formats them using
  `AGENT_MD_FORMAT`.
- `generate_single_file()` -- Runs `run_auto_conversation` with a `ReadTool` to
  generate one document. Validates JSON structure and writes to disk.
- `process_project_files()` -- Processes all files for one project, supporting both
  sequential and parallel execution.
- `label_documents()` -- Parallel labeling of documents missing field metadata.
- `add_dataset_uuids()` -- Parallel UUID assignment.
- `write_question_cache()` -- Builds the projects cache for question generation.
- `_save_debug_response()` -- Saves failed LLM responses to a debug directory for
  inspection.

### LLM Usage

- Phase 1: Automated LLM conversations with a read tool, run in parallel across
  projects and files.
- Phase 2: LLM calls for field labeling, run in parallel.
- Phases 3 and 4 do not use the LLM.

### Inputs / Outputs

- **Input:** Project JSON files from `generated_data/projects/`, `company_overview.md`,
  `agents.md` files, source directory structure.
- **Output:** JSON documents under `generated_data/sources/`, field labels and UUIDs
  added to each document, `generation_cache/projects.json`.

### Notable Details

- The `agents.md` files are collected hierarchically: if a file is at
  `sources/slack/eng-platform/doc.json`, the script gathers agents.md from `sources/`,
  `sources/slack/`, and `sources/slack/eng-platform/` to provide layered generation
  guidance.
- Failed responses are saved to a debug directory for post-mortem analysis.
- Supports CLI arguments: `--project-parallelism`, `--project-file-parallelism`,
  `--labeling-parallelism`.

---

## Step 8: Generate Completeness Documents

**File:** `step_8_generate_completeness_documents.py`

### Purpose

Generates "completeness document sets" -- groups of documents designed so that a single
question requires information from all documents in the set to be fully answered. These
support high-recall evaluation questions that test whether a retrieval system can find
every relevant document, not just one.

### How It Works

1. Accepts a `--count` argument specifying how many completeness traces to generate.
2. For each trace, creates a fresh tool set: `WriteTool` (scoped to `SOURCES_DIR`,
   with `is_document_json=True`), `GlobTool` (restricted to `agents` pattern only),
   `ReadTool`, `RmTool` (can only delete files written in the current step), and
   `FinishTool`.
3. Randomly selects a question type (1--5) and generates a corresponding user prompt.
   Types 1--4 use existing question type templates; type 5 asks the LLM to invent a
   new type.
4. Runs a semi-interactive conversation: the LLM generates an initial response
   autonomously, then the user can provide feedback or corrections.
5. When the LLM calls the finish tool (passing the question text as `finish_info`),
   the script validates all written files (valid JSON, no nested dicts). On failure,
   all written files are deleted and an error is raised.
6. On success, adds field labels and dataset UUIDs to each document, then writes a
   completeness entry to `generation_cache/completeness.json` containing the question
   and the list of document UUIDs.

### Key Functions

- `validate_written_files()` -- Validates JSON structure of all files written in the
  current trace.
- `delete_written_files()` -- Cleans up on validation failure.
- `add_uuids_to_files()` -- Adds `dataset_doc_uuid` to each written file.
- `label_files()` -- Adds title/content field labels to each written file.
- `write_completeness_entry()` -- Appends to the completeness generation cache.
- `get_question_type_prompt()` -- Randomly selects a question type and returns the
  appropriate prompt.

### LLM Usage

- One LLM conversation per trace with glob, read, write, rm, and finish tools.
  Semi-interactive (LLM acts first, user can intervene).

### Inputs / Outputs

- **Input:** `company_overview.md`, `source_tree.txt`, `agents.md` files, user guidance.
- **Output:** JSON documents under `generated_data/sources/`,
  `generation_cache/completeness.json` entries.

### Notable Details

- The `GlobTool` is restricted via `required_pattern=r"agents"` to prevent the LLM
  from browsing arbitrary files -- it can only glob for `agents.md` files.
- The `RmTool` is configured with a `get_deletable_paths` callback that limits deletion
  to files written during the current trace.
- Deleted paths are synced back to the `WriteTool` tracking to keep state consistent.
- Validation failure causes immediate deletion of all files from the current trace and
  raises an exception, ensuring no malformed documents persist.

---

## Step 9: Generate Volume Documents

**File:** `step_9_generate_volume_documents.py`

### Purpose

Generates the bulk of the dataset's documents at scale. While Steps 7 and 8 produce
documents tied to specific projects or completeness questions, Step 9 fills each source
type up to its target volume as specified in the `agents.md` files. This is typically
the most time-consuming step, potentially generating thousands of documents.

### How It Works

Operates in three phases:

**Phase 1 -- Generate Volume Task Files (Parallel):**
For each source type, determines the target document count by reading the source's
top-level `agents.md` (first via rule-based regex extraction, falling back to an LLM
call). Subtracts pre-existing documents. Calls the LLM to produce a JSON mapping of
topic names to document counts (e.g., `{"sprint retros": 50, "design docs": 30}`).
Validates the total is within 10% of the target and retries with correction prompts if
not. Saves the result as a structured JSON file in `generated_data/volume/` with
metadata including `pre_existing_doc_count`, `total_docs_in_topics`, and
`remaining_doc_count`.

**Phase 2 -- Recursive Topic Splitting (Parallel):**
Any topic with more than 500 target documents is recursively split into smaller
sub-topics using the LLM. Each split produces a list of sub-topic names with counts,
validated against the parent count. The process recurses until all leaf topics are at
or below 500 documents. The volume JSON files are updated in place with nested
`sub_topics` structures.

**Phase 3 -- Document Generation (Highly Parallel):**
Collects all leaf topics across all sources that still need documents (`desired >
completed`). Uses a `ThreadPoolExecutor` with a dynamic work-scheduling loop: it
maintains a set of active topics (max 1 document per leaf topic at a time to avoid
duplicates), submits new work as slots become available, and processes completions
via `FIRST_COMPLETED` waiting.

For each document, the LLM receives the company overview, the source's directory tree,
all relevant `agents.md` content, a list of existing documents for that topic (to avoid
duplication), and the topic hierarchy. The `WriteTool` is configured with
`expected_source_type` validation, `conflict_message` for path collisions,
`allow_create_dirs=False`, and `terminate_on_success=True` (stops the conversation after
the first successful write). After writing, the document is post-processed with field
labeling and UUID assignment via `process_written_document()`. The volume JSON is
updated with the new completed count and file path.

### Key Functions

- `get_total_docs_for_source()` -- Extracts target volume from `agents.md` using
  rule-based parsing with LLM fallback.
- `extract_total_docs_rule_based()` / `extract_total_docs_llm()` -- Two strategies for
  reading target counts.
- `validate_volume_json()` -- Validates topic-to-count JSON structure.
- `check_estimation_accuracy()` -- Checks if LLM's topic totals are within 10% of
  the target.
- `normalize_volume_json()` -- Converts raw topic counts into the structured volume
  format with metadata.
- `generate_volume_for_source()` -- Full Phase 1 pipeline for one source type.
- `split_topic()` -- Splits one large topic into sub-topics via LLM.
- `recursively_split_topics()` -- Recursively splits until all topics are under the
  size limit.
- `collect_leaf_topics()` -- Traverses the nested topic tree to find all actionable
  leaf topics.
- `update_volume_completed()` -- Thread-safe update of completed counts and file lists
  in volume JSON.
- `get_existing_docs_for_topic()` -- Retrieves already-created document paths for a
  topic to help the LLM avoid duplication.
- `generate_single_document()` -- Generates one document with retries, post-processing,
  and volume tracking.
- `get_pending_work_items()` -- Finds leaf topics that need documents and are not
  currently being processed.
- `generate_documents()` -- The Phase 3 orchestrator with dynamic thread pool
  scheduling.

### LLM Usage

- Phase 1: LLM calls for topic generation and target count extraction. Automated
  (no user interaction).
- Phase 2: LLM calls for topic splitting. Automated with estimation accuracy retries.
- Phase 3: Uses `get_cheap_llm()` (a less expensive model) for individual document
  generation via `run_auto_conversation`. Each document gets its own automated
  conversation with a write tool.

### Inputs / Outputs

- **Input:** `company_overview.md`, `initiatives.md`, `agents.md` files, source
  directory structures.
- **Output:** Volume task files in `generated_data/volume/`, JSON documents under
  `generated_data/sources/`.

### Notable Details

- Phase 3 uses `get_cheap_llm()` instead of `get_llm()` to reduce costs for the
  high-volume document generation.
- The `WriteTool` in Phase 3 is configured with `terminate_on_success=True`, causing
  the auto-conversation to stop immediately after the first successful file write.
- Thread safety is achieved through per-source-type locks for volume file updates and
  an active-topics set with its own lock to prevent two workers from generating documents
  for the same leaf topic simultaneously.
- Supports `--doc-limit` to cap the total number of documents generated in a single run.
- Between Phase 2 and Phase 3, the script pauses for user confirmation, allowing manual
  review and editing of the volume topic breakdown before committing to large-scale
  generation.
- The `MAX_TOPIC_SIZE` constant (500) controls the recursive splitting threshold.
- Estimation accuracy is enforced at 10% tolerance; topics that exceed this after all
  retry attempts are flagged with warnings but still saved.
- Supports CLI arguments: `--source-parallelism`, `--topic-parallelism`,
  `--doc-parallelism`, `--doc-limit`.
