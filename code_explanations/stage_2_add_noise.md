# Stage 2: Add Noise -- Code Explanations

This document describes the four steps in `src/scripts/stage_2_add_noise/`. The overall goal of Stage 2 is to inject realistic noise and complexity into the generated dataset by shuffling documents into wrong directories, creating miscellaneous clutter files, and producing near-duplicate documents with subtly updated facts.

---

## Step 1: Random Shuffle (`step_1_random_shuffle.py`)

### Purpose

Randomly relocate a configurable percentage of JSON documents to different subdirectories within the same source type. This simulates the real-world phenomenon of files being misfiled or stored in non-ideal locations inside a company's knowledge base.

### How It Works

1. The script iterates over every top-level source type directory under `generated_data/sources/` (e.g., `slack`, `confluence`, etc.).
2. For each source type it collects all `.json` files and all subdirectories.
3. It randomly samples a percentage of the files (default 3%, configurable via `--percentage`).
4. Each selected file is moved to a randomly chosen subdirectory that is different from its current directory. The destination is picked by repeatedly sampling a random directory (up to 50 attempts) until one differs from the file's current parent.
5. Before writing the file to its new location, an `original_location` field is added to the JSON document recording where it originally lived (in `source_type/relative/path` format).
6. Filename collisions at the destination are handled by appending an incrementing counter suffix (e.g., `file_1.json`, `file_2.json`).
7. The original file is deleted after the new copy is successfully written.

### Key Functions

- `collect_json_files(source_type_dir)` -- Walks a directory tree and returns all `.json` file paths.
- `collect_directories(source_type_dir)` -- Walks a directory tree and returns all subdirectory paths (excluding the root).
- `pick_destination_dir(current_dir, all_dirs)` -- Randomly picks a directory different from the current one.
- `move_and_tag_file(file_path, dest_dir, source_type)` -- Loads the JSON, adds `original_location`, writes to the destination, and removes the original.
- `shuffle_source_type(source_type, percentage)` -- Orchestrates the shuffle for one source type.

### LLM Usage

None. This step is purely random.

### Inputs / Outputs

- **Input:** All `.json` files under `generated_data/sources/`.
- **Output:** A subset of those files are physically moved to different subdirectories within the same source type, with an `original_location` field injected into each moved document.
- **Statistics:** Writes aggregate stats (total documents, documents moved, shuffle percentage) via `update_statistics()`.

### Notable Details

- An optional `--seed` flag enables reproducible shuffles.
- Source types with no subdirectories are skipped since there is nowhere to move files.
- At least 1 file is always moved per source type (the count is `max(1, round(total * pct / 100))`).

---

## Step 2: LLM-Based Shuffle (`step_2_llm_based_shuffle.py`)

### Purpose

Move a percentage of documents to "neighboring" directories chosen by an LLM rather than at random. The LLM picks a destination that is plausible but suboptimal -- a directory that is related enough to seem reasonable yet clearly not the ideal home. This creates a more realistic form of misfiling noise than pure random placement.

### How It Works

1. Like Step 1, the script enumerates source types and samples a percentage of files per source type (default 5%).
2. For each selected file, the LLM is given the file's current path, its full JSON contents, and the directory tree of that source type.
3. The LLM is asked to output a single directory path -- a reasonable but non-ideal location for the document. The prompt specifically instructs it to prefer directories that are relevant but far from the original, or nearby directories if nothing further away fits.
4. The proposed directory is validated: the script strips common prefix issues (`sources/`, backticks, quotes), checks whether it exists on disk, and confirms it differs from the file's current directory. If validation fails, the LLM is asked again (up to 5 attempts via a conversational retry loop with an error message appended).
5. Once a valid directory is found, the file is moved using the same `move_and_tag_file` logic as Step 1 (adds `original_location`, handles filename collisions, deletes the original). An additional detail: `original_location` is inserted before the `dataset_doc_uuid` field to keep the UUID as the last field in the JSON.
6. All file-processing tasks across all source types are executed in parallel using `ThreadPoolExecutor` (default 50 workers).

### Key Functions

- `get_source_type_tree(source_type)` -- Returns the directory tree for a single source type, loading from a cached file at `SOURCE_TREE_PATH` if available.
- `validate_proposed_dir(proposed_dir, source_type)` -- Cleans up and validates the LLM's proposed directory against the actual filesystem.
- `pick_directory_with_llm(file_path, file_contents, source_type, source_tree)` -- Runs the multi-turn LLM conversation to select a destination directory.
- `process_single_file(task)` -- The unit of parallel work: loads a file, calls the LLM, and moves the file. Returns a `ShuffleResult` dataclass.

### Data Structures

- `ShuffleTask` (dataclass) -- Holds the absolute file path, source type, and source tree string for one unit of work.
- `ShuffleResult` (dataclass) -- Holds the outcome: source type, original relative path, new relative path (or `None`), and error message (or `None`).

### LLM Usage

- Uses `get_llm()` (the primary / more capable model) with no tools, in quiet mode.
- The prompt is defined in `src/prompts/neighboring_shuffle.py` as `SHUFFLE_PROMPT`. It provides the file path, file contents, and directory structure, and asks for just a directory path in return.
- On invalid responses, `PATH_ERROR_RESPONSE` is appended as a user message and the LLM retries (up to 5 total attempts per file).

### Inputs / Outputs

- **Input:** All `.json` files under `generated_data/sources/`.
- **Output:** A subset of files moved to LLM-chosen directories, each tagged with `original_location`.
- **Statistics:** Writes total documents, documents selected, documents moved, error count, and shuffle percentage.

### Notable Details

- Parallelism is configurable (`--parallelism`, default 50). Each file is independently processed, so the LLM calls happen concurrently.
- The script caps error reporting at 20 lines in the summary printout.
- Source types with no nested subdirectories are skipped entirely.

---

## Step 3: Generate Miscellaneous Files (`step_3_generate_misc_files.py`)

### Purpose

Create entirely new "miscellaneous" directories and populate them with LLM-generated noise documents. These represent the kind of unorganized, less-relevant files that accumulate in real company data stores -- files in a `random` Slack channel or a `new_folder` in Google Drive, for example.

### How It Works

The script operates in two distinct phases:

**Phase 1: Create Miscellaneous Directories (Interactive)**

1. The LLM is shown the full source directory tree and asked to propose new miscellaneous directories.
2. A custom `SingleLevelMkdirTool` restricts directory creation to one level at a time (the parent must already exist). This prevents the LLM from creating deeply nested structures.
3. The process runs as an interactive `Conversation` loop: the LLM proposes a directory, the user confirms, and the `mkdir` tool is called. The user can type `quit` or the LLM can call `FinishTool` to end the phase.
4. Created directory paths are saved to a persistent cache at `generation_cache/misc_dirs_and_files.json`.

**Phase 2: Generate Miscellaneous Files (Parallel)**

1. The script determines how many files still need to be created to reach the target count (default 20), subtracting any already tracked in the cache.
2. For each file to generate, `generate_single_misc_file()` is called. It uses `get_cheap_llm()` (the cheaper/faster model) with a `WriteTool` configured to auto-process documents (add field labels and UUID) and mark them as noise.
3. The LLM is given the company overview, the relevant `agents.md` files (found by walking up from each misc directory to the sources root), the list of misc directories, and the list of already-existing misc files (to encourage diversity).
4. File generation runs via `run_auto_conversation()` which loops the LLM automatically (no user input) until the `WriteTool` succeeds or max iterations are reached. The `WriteTool` is configured with `terminate_on_success=True` so the conversation stops as soon as a file is written.
5. Each successful file's UUID is appended to the cache, which is saved after every individual success for crash resilience.
6. Failures are retried up to 3 times per file. On error, any partially written files are cleaned up.

### Key Functions / Classes

- `SingleLevelMkdirTool` -- Custom tool class implementing `ToolInterface`. Validates that the parent directory exists before calling `os.mkdir`. Tracks all created directories in `created_dirs`.
- `create_misc_directories()` -- Runs the Phase 1 interactive conversation.
- `get_agents_md_for_misc_dirs(misc_directories)` -- Walks up ancestor paths of each misc directory collecting all `agents.md` files for context.
- `get_existing_misc_files(misc_directories)` -- Lists existing `.json` files in the misc directories.
- `generate_single_misc_file(...)` -- Generates one file using auto-conversation with the cheap LLM.
- `generate_misc_files(...)` -- Orchestrates Phase 2 with `ThreadPoolExecutor` and a `tqdm` progress bar.
- `load_cache()` / `save_cache(cache)` -- Persist and load the `{"directories": [...], "files": [...]}` cache dict.

### LLM Usage

- **Phase 1:** Uses `get_llm()` (primary model) with `SingleLevelMkdirTool` and `FinishTool` registered as tools. The system prompt is `MISC_FILES_SYSTEM_PROMPT` from `src/prompts/misc_files.py`.
- **Phase 2:** Uses `get_cheap_llm()` (cheaper model) with `WriteTool` as the only tool. The prompt is `MISC_FILES_PROMPT`, which instructs the LLM to generate a JSON document conforming to the source type's schema (from `agents.md`) while being as different as possible from existing misc files.

### Inputs / Outputs

- **Input:** The source directory tree, company overview (`generated_data/company_overview.md`), and `agents.md` files.
- **Output:** New directories created under source types, and new `.json` files written into those directories. Each file is auto-processed to include field labels and a `dataset_doc_uuid`. Files are marked as noise.
- **Cache:** `generation_cache/misc_dirs_and_files.json` tracks directories and file UUIDs.
- **Statistics:** Total directories, total files, directory list, and per-source-type directory counts.

### Notable Details

- Phase 1 is interactive (requires user confirmation for each directory), while Phase 2 is fully automated and parallelized.
- The cache enables resumability: if the script is restarted, it skips Phase 1 if directories already exist in the cache and only generates the remaining files needed to reach the target count.
- The `WriteTool` is configured with `mark_as_noise=True`, which flags these documents as noise in the dataset.
- Thread safety for the shared `created_files` list is managed via a `threading.Lock`.
- Default parallelism for file generation is 5 (lower than Step 2, since each file generation involves a multi-turn auto-conversation).

---

## Step 4: Generate Near-Duplicate Files (`step_4_generate_near_duplicates.py`)

### Purpose

Create near-duplicate versions of existing documents to simulate the real-world scenario where outdated documents coexist with newer versions in different locations. The near-duplicates cover the same topic but have some facts updated, and they may reside in an entirely different source type with a correspondingly different schema.

### How It Works

The script runs a sequential loop (default 20 iterations), and each iteration goes through three phases:

**Phase 1a: Generate New File Path**

1. A source file is selected using `select_random_file_hierarchical()`, which performs a weighted random walk through the directory tree. The script tries to avoid picking the same source file twice (up to 10 retries).
2. The LLM is given the original file path, its contents, and the full source directory tree, and asked to propose a new file path (which may be in a completely different source type).
3. The proposed path is cleaned up (stripped of markdown formatting, `sources/` prefix) and validated to ensure the parent directory exists. Invalid proposals trigger conversational retries (up to 5 attempts).

**Phase 1b: Rename File for Source Type**

4. Once a valid directory is determined, the LLM is asked a follow-up question to rename the file according to the naming conventions of the target source type. The relevant `agents.md` files are provided for context.
5. The proposed filename is validated to ensure it does not collide with an existing file and differs from the original path. Up to 3 rename attempts are made.

**Phase 2: Generate New File Contents**

6. The LLM is given the original path, original contents, `agents.md` for the target source type, and the new file path. It generates updated JSON contents that preserve the core topic but change some facts.
7. The response is parsed as JSON with multiple fallback strategies: direct `json.loads`, `extract_json_from_response` (brace-matching/regex), and `try_recover_json` (LLM-based JSON repair). The result is validated to ensure no nested dicts (all values must be strings, primitives, or lists of strings).
8. The validated JSON is written using `WriteTool` configured with `is_document_json=True`, `mark_as_noise=True`, and `auto_process=True` (which adds field labels and a UUID).

**Cache and Tracking**

9. On success, a `{"document_old": old_uuid, "document_new": new_uuid}` entry is appended to the `duplications_cache` (stored at `generation_cache/duplications.json`), linking the original and duplicate documents by UUID.

### Key Functions

- `generate_new_file_path(file_path, file_contents, source_tree)` -- Runs Phase 1a: asks the LLM for a new directory and file path, validates it, then calls `_rename_file_for_source` for Phase 1b.
- `_rename_file_for_source(new_path, file_path, messages, llm)` -- Phase 1b: asks the LLM to rename the file following target source type conventions.
- `generate_new_file_contents(file_path, file_contents, new_file_path)` -- Phase 2: asks the LLM to produce updated JSON content for the near-duplicate.
- `generate_near_duplicate(file_path, source_tree)` -- Orchestrates all phases for a single document. Returns a `(success, message, old_path, new_path)` tuple.
- `validate_file_path(file_path)` -- Checks that the parent directory of a proposed path exists on disk.

### LLM Usage

- All phases use `get_llm()` (the primary model) with no tools (direct text generation).
- **Phase 1a** uses `FILE_MOVE_PROMPT` from `src/prompts/new_duplicate_file.py`. On invalid paths, `FILE_PATH_INVALID_RESPONSE` is appended as a retry message.
- **Phase 1b** uses `FILE_RENAME_PROMPT`, which includes the relevant `agents.md` content.
- **Phase 2** uses `NEW_DUPLICATE_FILE_PROMPT` as a system message and `NEW_DUPLICATE_FILE_USER_PROMPT` as the user message. The prompt instructs the LLM to keep the majority of the content and topic the same while updating some facts, and to adjust the schema if the target source type differs from the original.

### Inputs / Outputs

- **Input:** Existing `.json` files under `generated_data/sources/`, selected at random.
- **Output:** New `.json` files written to (potentially different) locations under `generated_data/sources/`. Each new file is auto-processed with field labels and a UUID, and marked as noise.
- **Cache:** `generation_cache/duplications.json` stores pairs of `{document_old, document_new}` UUIDs.
- **Statistics:** Target count, successfully created count, and failure count.

### Notable Details

- Unlike the other steps, this one runs sequentially (no parallelism), because each iteration is interactive with printed output showing the LLM's responses.
- The JSON recovery pipeline is thorough: raw parse, then regex/brace extraction, then LLM-based repair via `try_recover_json`.
- The `WriteTool` handles the final write including document post-processing (field labeling, UUID assignment, noise marking).
- The script tracks `used_source_files` to try to avoid generating multiple near-duplicates from the same original document, though it gives up after 10 retries and proceeds with whatever file it has.
- Cross-source-type duplication is explicitly supported: a Confluence document can produce a near-duplicate in Slack, for example, and the LLM is expected to adapt the schema accordingly.
