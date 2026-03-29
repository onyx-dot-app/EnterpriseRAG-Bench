# Project Guidelines

## Python Style

- Use modern union syntax `a | b` instead of `Union[a, b]`
- Use pydantic models instead of dataclasses
- Provide typing in all reasonable places
- Place imports at top of file
- Reference the utils directory to not rewrite functionality

## Code Quality

**Pre-commit hooks** run **black** (formatter) and **mypy** (type checker) on all files under `src/`. Both must pass before committing:
- **black** (v24.10.0) — all code must be formatted with black defaults
- **mypy** (v1.13.0) — strict type checking with `pydantic`, `types-PyYAML`, `types-requests` stubs

All changes to `src/` must satisfy both tools. Run `pre-commit run --all-files` to check locally.

## Script Docstring Convention

Every runnable script under `src/scripts/` must include a module-level docstring with:
1. A description of what the script does
2. A `Usage:` section with the full `python -m` invocation path
3. An `Args:` section listing CLI arguments (if any), or "No arguments." if interactive/argless

Example:
```python
"""Short description of what the script does.

Longer explanation of behavior, outputs, etc.

Usage:
    python -m src.scripts.<subpackage>.<module_name> [OPTIONS]

Args:
    --flag-name    Description of flag (default: value)
"""
```

## Project Structure

- `src/paths.py` - Centralized path constants for all generated data directories and files
- `src/llm/` - LLM provider abstraction layer
- `src/tools/` - Tool implementations for LLM agents
- `src/utils/` - Shared utility functions
- `src/schemas/` - Pydantic models for data validation
- `src/prompts/` - Prompt templates for various generation steps
- `src/scripts/` - All runnable scripts, organized by purpose:
  - `data_gen_stage_1_generate_clean_data/` - Stage 1: company overview, initiatives, employees, source structure, projects, documents
  - `data_gen_stage_2_add_noise/` - Stage 2: shuffling, misc files, near-duplicate generation
  - `data_gen_stage_3_generate_questions/` - Stage 3: 10 question type generators (basic, semantic, intra-doc reasoning, project, constrained, conflicting, completeness, miscellaneous, high-level, unanswerable)
  - `data_gen_stage_4_data_export/` - Stage 4: export final dataset
  - `answer_generation/` - Answer generation pipelines (agent-based retrieval, vector retrieval, Qdrant indexing)
  - `answer_evaluation/` - Evaluation harnesses (metrics-based eval, comparative eval)
  - `util_scripts/` - Maintenance utilities (file counting, label/UUID enforcement, cleanup)

## Utilities (`src/utils/`)

### File Operations
- **`file_io.py`** - Core file I/O: `load_file()`, `load_json_file()`, `write_json_file()` (atomic writes), `delete_file()`
- **`file_selection.py`** - Random file selection: `select_random_file_hierarchical()`, `count_json_files()`, `dir_has_json_files()`
- **`path_resolver.py`** - Path conversion between relative/absolute formats. Provides `PathResolver` class with `to_absolute()`, `to_relative()`, `exists()`, `is_file()`, `is_dir()`. Includes `default_resolver` and `sources_resolver` instances. Also provides `validate_source_path(file_path, expected_source_type)` for validating paths against a specific source type directory, and `normalize_source_path(file_path, expected_source_type)` for normalizing paths relative to SOURCES_DIR.

### JSON Handling
- **`json_extraction.py`** - `extract_json_from_response()` - Extracts JSON from LLM responses using multiple fallback strategies (braces matching, markdown blocks, regex)
- **`json_recovery.py`** - `try_recover_json()` - Uses LLM to fix broken JSON with conversation-based retries. Raises `JsonRecoveryError` on failure.
- **`validation.py`** - `validate_no_nested_dicts()`, `is_simple_value()` - Validates JSON structure constraints

### Document Processing
- **`document_processing.py`** - `process_written_document()` - Adds field labels and UUID to written documents (call after validation)
- **`document_content.py`** - `extract_document_content()` - Extracts title and content from labeled documents. Raises `DocumentFieldError` on missing fields.
- **`field_labeling.py`** - `label_document_fields()`, `label_single_document()`, `get_documents_without_labels()` - LLM-based field labeling to identify title/content fields
- **`field_ordering.py`** - `reorder_document_fields()`, `needs_reordering()` - Ensures trailing fields (title_field_name, content_field_names, dataset_doc_uuid) are at end of documents
- **`dataset_id.py`** - `generate_dataset_doc_uuid()`, `add_dataset_doc_uuid()`, `get_dataset_doc_uuid()` - UUID generation and management for documents
- **`directory_tree.py`** - `get_directory_tree()` - Pure Python directory tree representation (directories only, no `tree` command dependency)

### Question Generation
- **`questions.py`** - Shared utilities for question generation scripts. **Always check here before writing question generation code.**
  - `save_question()` - Standardized writer for `questions.jsonl`. Enforces consistent field order (`question_id`, `source_types`, `question`, `expected_doc_ids`, `gold_answer`, `answer_facts`, `question_type`). All question generation steps must use this instead of writing question dicts directly.
  - `generate_question()`, `validate_question()` - LLM-based question generation and validation
  - `extract_answer_facts()`, `extract_anti_hallucination_facts()` - Fact extraction from gold answers
  - `load_document()` - Load and extract UUID/title/content from a source document
  - `count_existing_questions()`, `get_next_question_id()`, `get_existing_doc_uuids()` - Question file state queries
  - `append_to_jsonl()`, `extract_source_type()` - Low-level helpers
- **`document_index.py`** - UUID-based document lookup and indexing
  - `load_or_build_uuid_index()` - Load UUID index from cache or build from disk
  - `ensure_uuids_resolved(needed_uuids, uuid_index=None)` - Load UUID index and **automatically rebuild once** if any needed UUIDs are missing. All question generation scripts should use this instead of `load_or_build_uuid_index()` when they have a known set of required UUIDs.
  - `rebuild_uuid_index()` - Force-rebuild the UUID index from disk
  - `load_document_content_by_uuid()`, `load_document_json_by_uuid()` - Load document data by UUID

### Evaluation Utilities
- **`eval_utils.py`** - Shared utilities for answer evaluation scripts
  - `load_questions()`, `load_answers()`, `load_updated_questions()` - Data loading helpers
  - `normalize_document_ids()`, `build_document_path_map()`, `resolve_document_path_map()` - Document ID validation and resolution
  - `strip_answer_citations()`, `evaluate_documents()`, `evaluate_documents_with_consensus()` - LLM-based evaluation (three-judge consensus voting)
  - `update_gold_answer()`, `validate_single_fact()` - Gold answer update and fact validation
  - `dedupe_doc_ids()`, `group_results_by_type()`, `sort_question_results()`, `build_type_order()` - Result organization helpers

### Generation Cache
- **`generation_cache.py`** - `GenerationCache` class with thread-safe `load()`, `append()`, `write_all()`, `count()` methods. Stores consolidated JSON arrays in `generation_cache/`. Four singleton instances:
  - `projects_cache` → `generation_cache/projects.json` (key: `"projects"`)
  - `completeness_cache` → `generation_cache/completeness.json` (key: `"completeness"`)
  - `duplications_cache` → `generation_cache/duplications.json` (key: `"duplications"`)
  - `misc_files_cache` → `generation_cache/misc_dirs_and_files.json` (key: `"files"`)

### Other Utilities
- **`cli.py`** - `confirm_yes_no()`, `confirm_regenerate()` - Interactive CLI prompts for user confirmation
- **`dates.py`** - `get_current_date_formatted()` - Returns current date as "Month DD, YYYY"
- **`statistics.py`** - `update_statistics(stage_name, step_name, stats)` - Tracks aggregate statistics across pipeline stages/steps (JSON format)
- **`agents_md.py`** - `get_agents_md_for_source()`, `get_agents_md_for_path()` - Retrieves agents.md content for source types

## LLM Layer (`src/llm/`)

- **`__init__.py`** - Re-exports: `get_llm`, `get_cheap_llm`, `LLMInterface`, `Message`, `ReasoningLevel`, `ToolCall`, `run_auto_conversation`
- **`interface.py`** - Abstract `LLMInterface` class, `Message` and `ToolCall` pydantic models, `ReasoningLevel` type
- **`factory.py`** - `get_llm()`, `get_cheap_llm()` - Factory functions based on `LLM_PROVIDER` env var (supports "openai", "anthropic")
- **`conversation.py`** - `Conversation` class for interactive conversation loops with tool calling support
- **`auto_conversation.py`** - `run_auto_conversation()` - Runs LLM conversations automatically without user input until completion
- **`openai_llm.py`** / **`anthropic_llm.py`** - Provider-specific implementations
- **`tracing.py`** - Braintrust tracing utilities: `init_tracing()`, `traced_span()`, `log_to_span()`, `get_current_span()`, `flush_traces()`. All no-ops when `BRAINTRUST_API_KEY`/`BRAINTRUST_PROJECT` env vars are not set.

## Tools (`src/tools/tool_implementations/`)

Tools that can be registered with `ToolRunner` for LLM agent use:

- **`ReadTool`** - Read file contents
- **`DocumentReadTool`** - ReadTool subclass that extracts document title/content and tracks reads
- **`WriteTool`** - Write content to files (with optional validation, base_dir, path override)
- **`GlobTool`** - Find files by glob pattern
- **`GrepTool`** - Search file contents by text pattern
- **`LsTool`** - List directory contents
- **`TreeTool`** - Display directory tree structure
- **`MkdirTool`** - Create directories
- **`RmdirTool`** - Remove directories
- **`MvdirTool`** - Move/rename directories
- **`RmTool`** - Remove files
- **`FinishTool`** - Signal step completion (has `finished` property and `reset()` method)
- **`ScratchpadTool`** - Temporary note storage during agent execution
- **`UpdateTasksTool`** - Update task tracking information
- **`ReadEmployeeDirectoryTool`** - Read employee directory data

## Schemas (`src/schemas/`)

- **`field_labels.py`** - `FieldLabels` model, `validate_field_labels()`, `parse_field_labels()`, `validate_field_labels_against_document()`
- **`employee_directory.py`** - Employee directory schema
- **`project_enrichment.py`** - Project enrichment data schema

## Key Paths (`src/paths.py`)

```python
GENERATED_DATA_DIR = "generated_data"
SOURCES_DIR = "generated_data/sources"
COMPANY_OVERVIEW_PATH = "generated_data/company_overview.md"
INITIATIVES_PATH = "generated_data/initiatives.md"
EMPLOYEE_DIRECTORY_PATH = "generated_data/employee_directory.yaml"
VISUAL_EMPLOYEE_DIRECTORY_PATH = "generated_data/visual_employee_directory.txt"
PROJECTS_DIR = "generated_data/projects"
PROJECT_LIST_PATH = "generated_data/project_list.txt"
SOURCE_TREE_PATH = "generated_data/source_tree.txt"
DEBUG_DIR = "generated_data/debug"
AGGREGATE_STATISTICS_PATH = "generated_data/aggregate_statistics.json"
VOLUME_DIR = "generated_data/volume"
COMPLETENESS_DIR = "generated_data/completeness"
QUESTIONS_PATH = "generated_data/questions.jsonl"
EXPORT_DATA_DIR = "export_data"
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_PROVIDER` | LLM backend (`"openai"` or `"anthropic"`) | `"openai"` |
| `LLM_API_KEY` | API key for the LLM provider | — |
| `LLM_MODEL_NAME` | Primary model name | Provider default |
| `CHEAP_LLM_MODEL_NAME` | Cheap/fast model name | Provider default |
| `BRAINTRUST_API_KEY` | Braintrust tracing API key (optional) | — |
| `BRAINTRUST_PROJECT` | Braintrust project name (optional) | — |
