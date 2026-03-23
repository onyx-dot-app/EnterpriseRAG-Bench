# Utilities Scripts Overview

Scripts in `src/data_scripts/utilities/` are standalone maintenance and cleanup tools for the generated data pipeline. Each operates on the `generated_data/sources/` directory (or a user-specified directory) and can be run directly from the command line.

---

## ensure_files_have_uuid.py

**Purpose:** Ensures every JSON document file in the sources directory has a `dataset_doc_uuid` field and that the trailing metadata fields are in the correct order.

**How it works:**

1. Accepts an optional directory argument (defaults to `SOURCES_DIR`). Walks the directory tree and collects all `.json` files.
2. For each file, loads the JSON and checks two conditions:
   - Whether the `dataset_doc_uuid` key is missing.
   - Whether the document's field ordering is incorrect (checked via `needs_reordering()`).
3. Files that satisfy neither condition are skipped. For the rest:
   - If a UUID is missing, `add_dataset_doc_uuid()` is called, which also fixes field ordering in the same pass.
   - If only reordering is needed, the document is loaded, reordered via `reorder_document_fields()`, and written back.
4. Prints a summary of how many files had UUIDs added, how many had ordering fixed, and how many failed.

**Key functions:**
- `main()` -- CLI entry point with `argparse`.

**Inputs/Outputs:**
- Input: Directory of JSON files (default `generated_data/sources`).
- Output: Mutates JSON files in-place by adding `dataset_doc_uuid` and/or reordering trailing fields.

**Notable details:** Files that fail to load (e.g., corrupt JSON) are silently skipped during the scanning phase and logged as failures during the processing phase. The `add_dataset_doc_uuid` utility performs both UUID insertion and field reordering in a single operation, so the script avoids double-processing.

---

## ensure_files_have_labels.py

**Purpose:** Ensures every JSON document file has LLM-assigned field labels (`title_field_name` and `content_field_names`) and correct trailing-field ordering. This is the labeling counterpart to `ensure_files_have_uuid.py`.

**How it works:**

1. Accepts an optional directory argument and a `--parallelism` flag (default 20). Walks the tree to find all `.json` files.
2. Checks each file for missing `title_field_name` or `content_field_names` keys and for incorrect field ordering.
3. Dispatches work to a `ThreadPoolExecutor`. Each worker calls `label_single_document()` (which invokes an LLM to identify which fields in the document represent the title and content) for files needing labels, or `reorder_document_fields()` for files that only need reordering.
4. Progress is displayed with a `tqdm` progress bar. When parallelism is greater than 1, labeling runs in quiet mode to avoid interleaved console output.
5. Prints a final summary and lists up to 20 failed files with their error messages.

**Key functions:**
- `main()` -- CLI entry point.
- `process_file(filepath, file_needs_labels, file_needs_reorder)` -- Inner helper submitted to the thread pool. Returns a tuple of `(success, message, did_label, did_reorder)`.

**Inputs/Outputs:**
- Input: Directory of JSON files, parallelism level.
- Output: Mutates JSON files in-place by adding field labels and/or fixing field order.

**Notable details:** Labeling requires LLM calls, so the parallelism flag directly controls throughput and API cost. The `label_single_document` function also handles ordering fixes when `fix_ordering=True`, so files needing both are processed in a single pass.

---

## count_total_files.py

**Purpose:** Counts and displays the number of JSON files per top-level source type in the sources directory. A quick inventory/reporting tool.

**How it works:**

1. Walks the `SOURCES_DIR` tree and counts `.json` files.
2. Groups counts by the first path component relative to `SOURCES_DIR` (e.g., `slack`, `confluence`, `jira`), which represents the source type.
3. Prints a formatted table sorted by count descending, with a total at the bottom.

**Key functions:**
- `count_json_files_per_source() -> dict[str, int]` -- Returns a dictionary mapping source type names to file counts. Can be imported and used programmatically.
- `main()` -- Prints the formatted report.

**Inputs/Outputs:**
- Input: None (always reads from `SOURCES_DIR`).
- Output: Prints a summary table to stdout. No files are modified.

**Notable details:** Uses `collections.Counter` for accumulation. The output is right-aligned with comma-formatted numbers for readability.

---

## remove_failed_jsons.py

**Purpose:** Finds and deletes JSON files that are empty, contain empty objects/arrays, or have invalid JSON syntax. Acts as a garbage collector for failed generation artifacts.

**How it works:**

1. Accepts an optional directory argument and a `--yes`/`-y` flag to skip the confirmation prompt.
2. Walks the directory tree and validates each `.json` file through `is_valid_json_file()`, which checks for:
   - Empty file (whitespace only).
   - Valid JSON parse.
   - Non-empty content (rejects `{}` and `[]`).
3. Lists all invalid files with their failure reasons.
4. Unless `--yes` is passed, prompts the user for confirmation before deletion.
5. Deletes invalid files and prints a summary.

**Key functions:**
- `is_valid_json_file(filepath) -> tuple[bool, str]` -- Validates a single file. Returns a boolean and a human-readable reason string on failure.
- `main()` -- CLI entry point.

**Inputs/Outputs:**
- Input: Directory of JSON files (default `generated_data/sources`).
- Output: Deletes invalid files from disk.

**Notable details:** The confirmation prompt is a safety measure; the `--yes` flag allows use in automated pipelines. The validation intentionally treats `{}` and `[]` as invalid because they represent generation failures that produced no meaningful content.

---

## denoise_moved_docs.py

**Purpose:** Reverts documents that were previously shuffled (moved to a different directory) back to their original locations. This undoes a "noise" step in the data pipeline where documents are intentionally misplaced to test retrieval robustness.

**How it works:**

1. Scans all JSON files under `SOURCES_DIR` for an `original_location` field, which records where the document lived before being moved.
2. For each found document, `restore_document()`:
   - Reads the JSON and extracts the `original_location` (a path relative to `SOURCES_DIR`).
   - Checks that the original directory still exists.
   - Removes the `original_location` field from the document data.
   - Handles filename collisions at the destination by appending a counter suffix (e.g., `_1`, `_2`).
   - Writes the cleaned document to the destination and deletes the file at the current location (unless source and destination are the same path).
3. Prints each restoration as it happens and a final summary.

**Key functions:**
- `find_moved_documents() -> list[str]` -- Scans for all documents containing `original_location`.
- `restore_document(file_path) -> tuple[bool, str]` -- Moves a single document back. Returns success status and a message describing the move or error.
- `main()` -- CLI entry point.

**Inputs/Outputs:**
- Input: The `generated_data/sources` directory tree.
- Output: Moves files back to their original locations, removes the `original_location` field from each, and deletes the displaced copies.

**Notable details:** The collision-handling logic ensures no data is lost if a file already exists at the original location. The script uses `os.path.abspath` comparison to avoid deleting a file when source and destination resolve to the same path (which can happen if a document was "moved" within the same directory).

---

## clean_up_volume_docs.py

**Purpose:** Tracks which document UUIDs are associated with non-volume pipeline stages (projects, completeness, duplications) and provides an interactive cleanup workflow to delete orphaned source files and clear stale volume references.

**How it works:**

The script operates in two phases:

**Phase 1 -- UUID Collection and Tracking:**
1. Loads three generation caches (`projects_cache`, `completeness_cache`, `duplications_cache`) and extracts all document UUIDs referenced by each.
2. Writes a tracker file to `debug/non_volume_documents.json` listing UUIDs grouped by source (projects, completeness, duplication).

**Phase 2 -- Interactive Cleanup (optional, prompted):**
1. Combines all tracked UUIDs into a single set.
2. Scans every `.json` file under `SOURCES_DIR` and identifies "orphaned" files whose `dataset_doc_uuid` is not in the tracked set (or is missing entirely).
3. Reads all volume JSON files (`volume/*.json`) and recursively collects file paths from their `topics` and `sub_topics` hierarchies.
4. Computes three groups: files only orphaned, files only in volume references, and files in both.
5. Shows a summary and example files, then prompts for a second confirmation.
6. On confirmation, deletes the identified files from disk, then clears all `files` arrays in the volume JSON topic/sub-topic trees and rewrites those files.

**Key functions:**
- `get_project_uuids()`, `get_completeness_uuids()`, `get_duplication_uuids()` -- Extract UUIDs from each respective cache.
- `collect_files_from_topic(topic_data) -> list[str]` -- Recursively collects file paths from a topic dict including nested `sub_topics`.
- `get_volume_file_paths(volume_dir) -> set[str]` -- Aggregates all file paths from all volume JSON files.
- `clear_files_from_topic(topic_data) -> int` -- Recursively empties `files` lists in a topic tree, returning the count cleared.
- `clear_volume_file_references(volume_dir) -> int` -- Clears file references across all volume JSONs.
- `find_orphaned_source_files(sources_dir, all_tracked_uuids) -> list[Path]` -- Identifies source files not matching any tracked UUID.
- `cleanup_files(files_to_delete) -> int` -- Deletes a list of files.
- `main()` -- Orchestrates both phases with interactive prompts.

**Inputs/Outputs:**
- Input: Generation caches (`generation_cache/projects.json`, `completeness.json`, `duplications.json`), source files under `generated_data/sources`, volume files under `generated_data/volume`.
- Output: Writes `debug/non_volume_documents.json`. Optionally deletes orphaned source files and clears file references in volume JSONs.

**Notable details:** The script uses two layers of confirmation (`confirm_yes_no`) -- one to enter cleanup mode and another before actually deleting files. The volume file path collection is recursive through `sub_topics`, which can be arbitrarily nested. Files that cannot be read are conservatively treated as orphaned.
