# Project Guidelines

## Python Style

- Use modern union syntax `a | b` instead of `Union[a, b]`
- Use pydantic models instead of dataclasses
- Provide typing in all reasonable places
- Place imports at top of file
- Reference the utils directory to not rewrite functionality

## Project Structure

- `src/paths.py` - Centralized path constants for all generated data directories and files
- `src/llm/` - LLM provider abstraction layer
- `src/tools/` - Tool implementations for LLM agents
- `src/utils/` - Shared utility functions
- `src/schemas/` - Pydantic models for data validation
- `src/prompts/` - Prompt templates for various generation steps
- `src/data_scripts/` - Scripts for data generation pipeline stages

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

### Other Utilities
- **`cli.py`** - `confirm_yes_no()`, `confirm_regenerate()` - Interactive CLI prompts for user confirmation
- **`dates.py`** - `get_current_date_formatted()` - Returns current date as "Month DD, YYYY"
- **`statistics.py`** - `update_statistics(stage_name, step_name, stats)` - Tracks aggregate statistics across pipeline stages/steps (JSON format)
- **`agents_md.py`** - `get_agents_md_for_source()`, `get_agents_md_for_path()` - Retrieves agents.md content for source types

## LLM Layer (`src/llm/`)

- **`interface.py`** - Abstract `LLMInterface` class, `Message` and `ToolCall` pydantic models
- **`factory.py`** - `get_llm()`, `get_cheap_llm()` - Factory functions based on `LLM_PROVIDER` env var (supports "openai", "anthropic")
- **`conversation.py`** - `Conversation` class for interactive conversation loops with tool calling support
- **`auto_conversation.py`** - `run_auto_conversation()` - Runs LLM conversations automatically without user input until completion
- **`openai_llm.py`** / **`anthropic_llm.py`** - Provider-specific implementations

## Tools (`src/tools/tool_implementations/`)

Tools that can be registered with `ToolRunner` for LLM agent use:

- **`ReadTool`** - Read file contents
- **`WriteTool`** - Write content to files (with optional validation, base_dir, path override)
- **`GlobTool`** - Find files by glob pattern
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
PROJECTS_DIR = "generated_data/projects"
VOLUME_DIR = "generated_data/volume"
COMPLETENESS_DIR = "generated_data/completeness"
QUESTIONS_PATH = "generated_data/questions.jsonl"
EXPORT_DATA_DIR = "export_data"
```
