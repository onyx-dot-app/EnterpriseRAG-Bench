"""Interactive script for generating completeness document sets."""

import argparse
import json
import os
import random

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    GENERATED_DATA_DIR,
    QUESTION_CACHE_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.completeness_documents import (
    COMPLETENESS_SYSTEM_PROMPT,
    COMPLETENESS_USER_PROMPT_EXISTING_TYPE,
    COMPLETENESS_USER_PROMPT_NEW_TYPE,
)
from src.utils.statistics import update_statistics
from src.tools import FINISH_TOOL
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, GlobTool, ReadTool, RmTool, WriteTool
from src.utils.dataset_id import add_dataset_doc_uuid
from src.utils.field_labeling import label_single_document
from src.utils.file_io import delete_file, load_file, load_json_file, write_json_file
from src.utils.validation import validate_no_nested_dicts


def validate_written_files(file_paths: list[str]) -> tuple[bool, list[str]]:
    """
    Validate that all written files are valid JSON with no nested dicts.

    Args:
        file_paths: List of paths relative to sources (e.g., "sources/confluence/doc.json")

    Returns:
        (is_valid, errors) tuple where errors is a list of error messages.
    """
    errors = []

    for rel_path in file_paths:
        # Convert sources/... to generated_data/sources/...
        full_path = os.path.join(GENERATED_DATA_DIR, rel_path)

        if not os.path.exists(full_path):
            errors.append(f"File not found: {rel_path}")
            continue

        try:
            data = load_json_file(full_path)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {rel_path}: {e}")
            continue

        validation_error = validate_no_nested_dicts(data)
        if validation_error:
            errors.append(f"Validation error in {rel_path}: {validation_error}")

    return (len(errors) == 0, errors)


def delete_written_files(file_paths: list[str]) -> None:
    """
    Delete all files that were written during this step.

    Args:
        file_paths: List of paths relative to sources (e.g., "sources/confluence/doc.json")
    """
    for rel_path in file_paths:
        full_path = os.path.join(GENERATED_DATA_DIR, rel_path)
        if delete_file(full_path):
            print(f"  Deleted: {rel_path}")


class JsonDocumentWriteTool(WriteTool):
    """
    WriteTool for writing JSON documents to the sources directory.

    Validates that:
    - File path ends with .json
    - File is in a subdirectory (not directly in sources root)
    - Parent directory exists
    - File doesn't already exist

    Tracks all written file paths for later reference.
    """

    def __init__(self, base_dir: str | None = None, allow_create_dirs: bool = False) -> None:
        super().__init__(base_dir=base_dir, allow_create_dirs=allow_create_dirs)
        self._written_paths: list[str] = []

    @property
    def written_paths(self) -> list[str]:
        """Return list of paths written since last reset."""
        return self._written_paths.copy()

    def reset_tracking(self) -> None:
        """Clear the list of written paths."""
        self._written_paths = []

    def remove_path(self, path: str) -> None:
        """Remove a path from tracking (called when file is deleted)."""
        # Try to remove with various formats
        for p in [path, f"sources/{path}"]:
            if p in self._written_paths:
                self._written_paths.remove(p)
                return

    def execute(self, content: str, file_path: str = "") -> str:
        """Write JSON content after validating path. Returns error if path invalid or file exists."""
        # Validate file path format
        if not file_path:
            return "Error: No file path provided. Please specify a valid .json file path."

        if not file_path.endswith(".json"):
            return f"Error: File path must end with .json, got: {file_path}. Please use a .json extension."

        # Check path has proper directory structure (not directly in base dir)
        normalized_path = self._normalize_path(file_path) if self._base_dir else file_path
        path_parts = normalized_path.replace("\\", "/").split("/")
        if len(path_parts) < 2:
            return f"Error: File must be in a subdirectory, not directly in sources root. Got: {file_path}"

        # Validate parent directory exists and file doesn't already exist
        if self._base_dir:
            target_path = os.path.join(self._base_dir, normalized_path)
            parent_dir = os.path.dirname(target_path)
            if not os.path.isdir(parent_dir):
                return f"Error: Parent directory does not exist: {parent_dir}. Please use an existing directory path."

            if os.path.exists(target_path):
                return f"Error: File already exists at {file_path}. Try with a new file name or path."

        result = super().execute(content, file_path)
        if result.startswith("Successfully wrote to "):
            # Extract the actual written path from the result
            actual_path = result.replace("Successfully wrote to ", "")
            # Convert to relative path from sources/
            if self._base_dir and actual_path.startswith(self._base_dir):
                rel_path = actual_path[len(self._base_dir):].lstrip("/")
                self._written_paths.append(f"sources/{rel_path}")
            else:
                self._written_paths.append(actual_path)
        return result


def count_existing_traces() -> int:
    """Count existing completeness trace files in question_cache."""
    if not os.path.exists(QUESTION_CACHE_DIR):
        return 0
    return len([f for f in os.listdir(QUESTION_CACHE_DIR) if f.startswith("completeness_") and f.endswith(".json")])


def get_next_trace_number() -> int:
    """Get the next available trace number."""
    if not os.path.exists(QUESTION_CACHE_DIR):
        return 1
    existing = [
        f for f in os.listdir(QUESTION_CACHE_DIR)
        if f.startswith("completeness_") and f.endswith(".json")
    ]
    if not existing:
        return 1
    numbers = []
    for f in existing:
        try:
            num = int(f.replace("completeness_", "").replace(".json", ""))
            numbers.append(num)
        except ValueError:
            pass
    return max(numbers) + 1 if numbers else 1


def add_uuids_to_files(file_paths: list[str]) -> list[str]:
    """
    Add dataset_doc_uuid to each file and return the list of UUIDs.

    Args:
        file_paths: List of paths relative to sources (e.g., "sources/confluence/doc.json")

    Returns:
        List of dataset_doc_uuids in the same order as file_paths.
    """
    uuids = []
    for rel_path in file_paths:
        full_path = os.path.join(GENERATED_DATA_DIR, rel_path)
        doc_uuid = add_dataset_doc_uuid(full_path)
        uuids.append(doc_uuid)
    return uuids


def label_files(file_paths: list[str]) -> None:
    """
    Add field labels (title_field_name, content_field_names) to each file.

    Args:
        file_paths: List of paths relative to sources (e.g., "sources/confluence/doc.json")
    """
    for rel_path in file_paths:
        full_path = os.path.join(GENERATED_DATA_DIR, rel_path)
        success, message = label_single_document(full_path, quiet=True)
        if not success:
            print(f"  Warning: Failed to label {rel_path}: {message}")


def write_question_cache(trace_number: int, question: str, document_uuids: list[str]) -> str:
    """Write a completeness question cache JSON file."""
    os.makedirs(QUESTION_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(QUESTION_CACHE_DIR, f"completeness_{trace_number:04d}.json")
    cache_data = {
        "question": question,
        "documents": document_uuids,
    }
    write_json_file(cache_path, cache_data)
    return cache_path


def get_question_type_prompt() -> tuple[int, str]:
    """
    Generate a random question type and return the corresponding user prompt.

    Returns:
        (question_type, user_prompt) tuple where question_type is 1-6.
    """
    question_type = random.randint(1, 5)
    if question_type <= 4:
        # Use existing question type
        user_prompt = COMPLETENESS_USER_PROMPT_EXISTING_TYPE.format(
            question_type_number=question_type
        )
    else:
        # Use new question type
        user_prompt = COMPLETENESS_USER_PROMPT_NEW_TYPE
    return question_type, user_prompt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate completeness document sets for high-recall questions."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of completeness traces to generate (default: 10)",
    )
    args = parser.parse_args()

    num_to_generate = args.count

    # Show existing traces
    existing_count = count_existing_traces()
    print("Step 8: Completeness Document Generator")
    print("=" * 40)
    print("This script generates completeness document sets for high-recall questions.")
    print("Each set consists of documents needed to exhaustively answer a question.")
    print()
    print(f"Existing completeness traces: {existing_count}")
    print()
    print(f"Will generate {num_to_generate} completeness trace(s).")
    print("Type 'quit' at any prompt to exit early.\n")

    # Load context files
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    source_tree = load_file(SOURCE_TREE_PATH)

    prompt = COMPLETENESS_SYSTEM_PROMPT.format(
        company_overview=company_overview,
        file_structure=source_tree,
    )

    traces_generated = 0
    quit_requested = False

    for i in range(num_to_generate):
        if quit_requested:
            break

        trace_number = get_next_trace_number()

        print()
        print("=" * 40)
        print(f"Generating trace {i + 1} of {num_to_generate} (will be saved as completeness_{trace_number:04d}.json)")
        print("=" * 40)
        print()

        # Create tools
        write_tool = JsonDocumentWriteTool(base_dir=SOURCES_DIR)
        glob_tool = GlobTool(
            base_dir=SOURCES_DIR,
            required_pattern=r"agents",
            pattern_error_message="You can only use the glob command on agents.md files.",
        )
        read_tool = ReadTool(base_dir=SOURCES_DIR)
        rm_tool = RmTool(
            base_dir=SOURCES_DIR,
            get_deletable_paths=lambda: write_tool.written_paths,
        )
        finish_tool = FinishTool()

        # Initialize LLM with tool schemas
        llm = get_llm(tools=[
            glob_tool.schema,
            read_tool.schema,
            write_tool.schema,
            rm_tool.schema,
            finish_tool.schema,
        ])

        # Create tool runner and register tools
        tool_runner = ToolRunner()
        tool_runner.register(glob_tool)
        tool_runner.register(read_tool)
        tool_runner.register(write_tool)
        tool_runner.register(rm_tool)
        tool_runner.register(finish_tool)

        # Create conversation with LLM and tool runner
        conversation = Conversation(llm=llm, tool_runner=tool_runner)

        # Generate random question type and get corresponding user prompt
        question_type, user_prompt = get_question_type_prompt()
        print(f"Question type: {question_type} ({'existing type' if question_type <= 4 else 'new type'})")
        print()

        # Add system prompt, then user prompt, and get initial response
        conversation.add_system_message(prompt)
        conversation.run_turn(user_prompt, exit_on_tools=[FINISH_TOOL])
        print()

        while True:
            # Check if finish tool was called
            if finish_tool.finished:
                question = finish_tool.finish_info or ""
                files = write_tool.written_paths

                if not question:
                    print("\nWarning: No question provided with finish. Please provide the question.")
                    finish_tool.reset()
                    continue

                if not files:
                    print("\nWarning: No files were written. Please write the documents first.")
                    finish_tool.reset()
                    continue

                # Validate all written files
                is_valid, validation_errors = validate_written_files(files)
                if not is_valid:
                    print("\n" + "=" * 40)
                    print("VALIDATION FAILED")
                    print("=" * 40)
                    for error in validation_errors:
                        print(f"  - {error}")
                    print()
                    print("Deleting all files from this step...")
                    delete_written_files(files)
                    raise ValueError(f"Validation failed for written files: {validation_errors}")

                # Add field labels to documents (must happen before UUID)
                print("\nAdding field labels to documents...")
                label_files(files)

                # Add dataset_doc_uuid to each file and get the UUIDs (always last)
                print("Adding dataset_doc_uuid to documents...")
                document_uuids = add_uuids_to_files(files)

                # Write the question cache with UUIDs
                cache_path = write_question_cache(trace_number, question, document_uuids)
                traces_generated += 1
                print(f"\nSaved to {cache_path}")
                print(f"  Question: {question}")
                print(f"  Document UUIDs: {document_uuids}")
                break

            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() == "quit":
                    print("Exiting early...")
                    quit_requested = True
                    break

                conversation.run_turn(user_input, exit_on_tools=[FINISH_TOOL])

                # Sync deleted paths - remove from write_tool tracking
                for deleted_path in rm_tool.deleted_paths:
                    write_tool.remove_path(deleted_path)

                print()

            except KeyboardInterrupt:
                print("\nExiting early...")
                quit_requested = True
                break

    # Update statistics
    total_traces = count_existing_traces()
    update_statistics("Step 8: Completeness Traces", {
        "total_traces": total_traces,
        "traces_generated_this_run": traces_generated,
    })

    print()
    print("=" * 40)
    print("Completeness generation complete!")
    print(f"Generated {traces_generated} trace(s) this session.")
    print(f"Total traces: {total_traces}")


if __name__ == "__main__":
    main()
