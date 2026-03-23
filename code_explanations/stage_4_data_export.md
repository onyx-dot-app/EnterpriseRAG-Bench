# Stage 4: Default Basic File Export

**File:** `src/data_scripts/stage_4_data_export/default_basic_file_export.py`

## Purpose

This script is the final stage of the data generation pipeline. It converts the
internally generated JSON source documents into plain text files suitable for
external consumption, optionally packaging them into zip archives. It also
supports an "Onyx format" that separates document metadata (title, ID) into a
dedicated JSON sidecar file within each zip.

## High-Level Workflow

1. Parse CLI arguments and environment variables into an `ExportConfig`.
2. Wipe and recreate the `export_data/` directory.
3. Walk every JSON file under `generated_data/sources/`, validate it, convert it
   to plain text, and write the result into a mirrored directory structure under
   `export_data/`.
4. Optionally create one or more zip archives from the exported text files.
5. Print summary statistics (files found, exported, skipped, errors).

## Key Data Models (Pydantic)

| Model | Role |
|---|---|
| `ExportConfig` | Holds all user-facing options: source filter list, zip creation toggle, max file limits, split-by-source flag, and Onyx format flag. |
| `ExportStats` | Accumulates counters during export: total files scanned, files exported, files skipped due to missing fields, and a list of error messages. |
| `FileMetadata` | Captures per-file metadata (filename, UUID, title) needed to produce the `.onyx_metadata.json` sidecar inside Onyx-format zips. The `full_path` field is internal-only and is used to match files to their zip but is excluded from the sidecar output. |

## Key Functions

### `validate_document(data: dict) -> tuple[bool, str | None]`

Checks that a JSON document is eligible for export. Two conditions must be met:

- The document contains a `dataset_doc_uuid` field.
- The shared utility `extract_document_content()` succeeds, which in turn
  requires `title_field_name`, `content_field_names`, and the actual fields
  they reference to all be present and valid.

Returns a `(is_valid, error_message)` tuple.

### `convert_to_text(data: dict, include_title: bool = True) -> str`

Converts a validated JSON document to a plain-text string. The output is
structured as:

- **With title (default):** The title on the first line, a blank line, then all
  content fields joined by newlines.
- **Without title (Onyx format):** Only the content fields, because the title is
  stored in the metadata sidecar instead.

Content fields that are lists are flattened by joining items with newlines.
Unlike `extract_document_content()`, this function intentionally omits field-name
headers from the output -- it produces clean, unadorned text.

### `get_export_filename(uuid: str, original_filename: str) -> str`

Produces a filename in the format `{uuid}__{original_name_without_extension}.txt`.
This embeds the document UUID directly into the filename for traceability.

### `export_files(config: ExportConfig) -> tuple[ExportStats, list[FileMetadata]]`

The core export loop. It:

1. Deletes any existing `export_data/` directory and creates a fresh one.
2. Lists source directories under `generated_data/sources/`, optionally filtered
   by `config.sources`.
3. Walks each source directory in sorted order, processing every `.json` file.
4. For each file: validates with `validate_document`, converts with
   `convert_to_text`, writes the `.txt` output into a mirrored subdirectory
   structure under `export_data/`.
5. Respects `config.max_files` as an early-exit cap on the total number of
   exported files (useful for testing).
6. Collects `FileMetadata` entries when Onyx format is enabled.

Returns both the statistics and the metadata list.

### `create_zip_archives(config, metadata_list) -> list[str]`

Creates zip archives from the already-exported text files. Supports several
strategies controlled by config flags:

| `split_by_source` | `max_files_per_zip` | Behavior |
|---|---|---|
| False | None | Single `dataset.zip` containing everything. |
| False | N | Multiple `dataset_slice_0001.zip`, `dataset_slice_0002.zip`, etc., each with at most N files. |
| True | None | One `{source}.zip` per top-level source directory. |
| True | N | Per-source zips further split into `{source}_slice_0001.zip`, etc. |

### `_create_single_zip(zip_path, files, base_dir, metadata_list)`

Low-level helper that writes one zip file. It stores files with paths relative to
`base_dir` and uses `ZIP_DEFLATED` compression. When a `metadata_list` is
provided (Onyx format), it filters the metadata to only the files present in this
particular zip and writes a `.onyx_metadata.json` entry at the archive root. The
sidecar contains an array of objects with `filename`, `id`, and `title` fields
(the internal `full_path` field is excluded).

### `main()`

Entry point. Parses CLI arguments, reads the `EXPORT_IN_ONYX_FORMAT` environment
variable, builds an `ExportConfig`, runs the export, and optionally creates zips.
If `export_data/` already exists, the user is prompted for confirmation before it
is wiped.

## CLI Arguments

| Argument | Type | Description |
|---|---|---|
| `--sources` | `str` (multiple) | Restrict export to specific top-level source directories (e.g., `confluence slack`). |
| `--create-zip` | flag | Package exported files into zip archive(s). |
| `--max-files-per-zip` | `int` | Cap files per zip, creating numbered slices. |
| `--max-files` | `int` | Cap total files exported (for testing). |
| `--split-by-source` | flag | Create a separate zip per source directory. |

The Onyx format is activated via the `EXPORT_IN_ONYX_FORMAT` environment variable
(accepts `1`, `true`, or `yes`, case-insensitive) rather than a CLI flag.

## Inputs and Outputs

**Inputs:**

- JSON document files under `generated_data/sources/`. Each document must have:
  - `dataset_doc_uuid` -- a unique identifier assigned earlier in the pipeline.
  - `title_field_name` -- the key whose value is the document title.
  - `content_field_names` -- a list of keys whose values form the document body.
  - The actual data fields referenced by the above.

**Outputs:**

- Plain text files written to `export_data/`, preserving the source directory
  hierarchy. Each file is named `{uuid}__{original_stem}.txt`.
- Optionally, one or more `.zip` archives in `export_data/`.
- When Onyx format is active, each zip includes a `.onyx_metadata.json` sidecar
  mapping filenames to their UUIDs and titles.

## Notable Implementation Details

- The export directory is always wiped clean before a new export run. The user
  receives a confirmation prompt if the directory already exists.
- Document validation reuses the shared `extract_document_content()` utility from
  `src/utils/document_content.py` rather than reimplementing field checks.
- The text conversion deliberately differs from `extract_document_content()` in
  one respect: it omits field-name headers even when there are multiple content
  fields, producing cleaner output for downstream consumers.
- Errors during individual file processing are caught and accumulated rather than
  halting the entire export. The first 10 errors are printed at the end.
- The Onyx metadata sidecar uses a `full_path` field internally on `FileMetadata`
  to correlate files across zip boundaries, but this field is stripped from the
  JSON output so the sidecar only contains `filename`, `id`, and `title`.
- Zip slicing uses 4-digit zero-padded indices (e.g., `_slice_0001.zip`) to
  maintain sort order.
