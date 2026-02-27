"""Interactive script for generating completeness document sets."""

import argparse
import json
import os
import random

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    QUESTION_CACHE_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.completeness_documents import (
    COMPLETENESS_SYSTEM_PROMPT,
    COMPLETENESS_USER_PROMPT_EXISTING_TYPE,
    COMPLETENESS_USER_PROMPT_NEW_TYPE,
)
from src.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, GlobTool, ReadTool, RmTool, WriteTool
from src.utils.dataset_id import add_dataset_doc_uuid
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
        # Convert sources/... to data_clean/sources/...
        full_path = os.path.join(DATA_CLEAN_DIR, rel_path)

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
        full_path = os.path.join(DATA_CLEAN_DIR, rel_path)
        if delete_file(full_path):
            print(f"  Deleted: {rel_path}")


class TrackingWriteTool(WriteTool):
    """WriteTool that tracks all written file paths."""

    def __init__(self, base_dir: str | None = None) -> None:
        super().__init__(base_dir=base_dir)
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
        """Write content and track the path."""
        result = super().execute(content, file_path)
        if result.startswith("Successfully wrote to"):
            # Extract the relative path from sources/
            if self._base_dir:
                # Normalize the path
                normalized = self._normalize_path(file_path)
                # Store path relative to sources directory
                self._written_paths.append(f"sources/{normalized}")
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
        full_path = os.path.join(DATA_CLEAN_DIR, rel_path)
        doc_uuid = add_dataset_doc_uuid(full_path)
        uuids.append(doc_uuid)
    return uuids


def write_question_cache(trace_number: int, question: str, document_uuids: list[str]) -> str:
    """Write a completeness question cache JSON file."""
    os.makedirs(QUESTION_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(QUESTION_CACHE_DIR, f"completeness_{trace_number}.json")
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
    question_type = random.randint(1, 6)
    if question_type <= 4:
        # Use existing question type
        user_prompt = COMPLETENESS_USER_PROMPT_EXISTING_TYPE.format(
            question_type_number=question_type
        )
    else:
        # Use new question type (5 or 6)
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
        print(f"Generating trace {i + 1} of {num_to_generate} (will be saved as completeness_{trace_number}.json)")
        print("=" * 40)
        print()

        # Create tools
        write_tool = TrackingWriteTool(base_dir=SOURCES_DIR)
        glob_tool = GlobTool(base_dir=SOURCES_DIR)
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
        conversation.run_turn(user_prompt)
        print()

        # Interactive loop for this trace
        trace_complete = False

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

                # Add dataset_doc_uuid to each file and get the UUIDs
                print("\nAdding dataset_doc_uuid to documents...")
                document_uuids = add_uuids_to_files(files)

                # Write the question cache with UUIDs
                cache_path = write_question_cache(trace_number, question, document_uuids)
                traces_generated += 1
                print(f"\nSaved to {cache_path}")
                print(f"  Question: {question}")
                print(f"  Document UUIDs: {document_uuids}")
                trace_complete = True
                break

            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() == "quit":
                    print("Exiting early...")
                    quit_requested = True
                    break

                conversation.run_turn(user_input)

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
