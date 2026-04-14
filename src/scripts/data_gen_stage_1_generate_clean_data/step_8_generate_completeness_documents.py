"""Interactive script for generating completeness document sets.

Generates small clusters of 4-10 highly related documents where every document in the
cluster is visible to the model during generation. Each cluster is anchored to a target
question so that answer-critical facts are spread across multiple documents, enabling
completeness-type question generation later.

Usage:
    python -m src.scripts.data_gen_stage_1_generate_clean_data.step_8_generate_completeness_documents [OPTIONS]

Args:
    --count        Number of completeness traces to generate (default: 10)
    --auto-accept  Automatically accept each trace without user confirmation
"""

import argparse
import json
import random

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.completeness_documents import (
    AUTO_CONTINUE_USER_MESSAGE,
    COMPLETENESS_SYSTEM_PROMPT,
    COMPLETENESS_USER_PROMPT_EXISTING_TYPE,
    COMPLETENESS_USER_PROMPT_NEW_TYPE,
)
from src.utils.statistics import update_statistics
from src.tools import FINISH_TOOL
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    FinishTool,
    GlobTool,
    ReadTool,
    WriteTool,
)
from src.utils.dataset_id import add_dataset_doc_uuid
from src.utils.field_labeling import label_single_document
from src.utils.file_io import delete_file, load_file, load_json_file
from src.utils.generation_cache import completeness_cache
from src.utils.path_resolver import sources_resolver
from src.utils.validation import validate_no_nested_dicts

STEP_OVERVIEW = """\
Generates small clusters of 4-10 related documents where every document is
fully visible to the model alongside the others. Each cluster is anchored to
a target question so answer-critical facts are spread across multiple documents.
Supports later completeness-type question generation.

Existing completeness traces: {existing_count}
Will generate {num_to_generate} completeness trace(s).
Type 'quit' at any prompt to exit early.
"""


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
        full_path = sources_resolver.to_absolute(rel_path)

        if not sources_resolver.exists(rel_path):
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
        file_paths: List of paths relative to GENERATED_DATA_DIR (e.g., "sources/confluence/doc.json")
    """
    for rel_path in file_paths:
        full_path = sources_resolver.to_absolute(rel_path)
        if delete_file(full_path):
            print(f"  Deleted: {rel_path}")


def count_existing_traces() -> int:
    """Count existing completeness traces in generation cache."""
    return completeness_cache.count()


def add_uuids_to_files(file_paths: list[str]) -> list[str]:
    """
    Add dataset_doc_uuid to each file and return the list of UUIDs.

    Args:
        file_paths: List of paths relative to GENERATED_DATA_DIR (e.g., "sources/confluence/doc.json")

    Returns:
        List of dataset_doc_uuids in the same order as file_paths.
    """
    uuids = []
    for rel_path in file_paths:
        full_path = sources_resolver.to_absolute(rel_path)
        doc_uuid = add_dataset_doc_uuid(full_path)
        uuids.append(doc_uuid)
    return uuids


def label_files(file_paths: list[str]) -> None:
    """
    Add field labels (title_field_name, content_field_names) to each file.

    Args:
        file_paths: List of paths relative to GENERATED_DATA_DIR (e.g., "sources/confluence/doc.json")
    """
    for rel_path in file_paths:
        full_path = sources_resolver.to_absolute(rel_path)
        success, message = label_single_document(full_path, quiet=True)
        if not success:
            print(f"  Warning: Failed to label {rel_path}: {message}")


def write_completeness_entry(question: str, document_uuids: list[str]) -> None:
    """Append a completeness entry to the generation cache."""
    completeness_cache.append(
        {
            "question": question,
            "documents": document_uuids,
        }
    )


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
    parser.add_argument(
        "--auto-accept",
        action="store_true",
        help="Automatically accept each trace without user input",
    )
    args = parser.parse_args()

    num_to_generate = args.count

    # Show existing traces
    existing_count = count_existing_traces()
    print("Step 8: Completeness Document Generator")
    print("=" * 40)
    print(
        STEP_OVERVIEW.format(
            existing_count=existing_count,
            num_to_generate=num_to_generate,
        )
    )

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

        trace_index = count_existing_traces() + 1

        print()
        print("=" * 40)
        print(
            f"Generating trace {i + 1} of {num_to_generate} (will be entry #{trace_index})"
        )
        print("=" * 40)
        print()

        # Create tools
        write_tool = WriteTool(base_dir=SOURCES_DIR, is_document_json=True)
        glob_tool = GlobTool(
            base_dir=SOURCES_DIR,
            required_pattern=r"agents",
            pattern_error_message="You can only use the glob command on agents.md files.",
        )
        read_tool = ReadTool(base_dir=SOURCES_DIR)
        finish_tool = FinishTool()

        # Initialize LLM with tool schemas
        llm = get_llm(
            tools=[
                glob_tool.schema,
                read_tool.schema,
                write_tool.schema,
                finish_tool.schema,
            ]
        )

        # Create tool runner and register tools
        tool_runner = ToolRunner()
        tool_runner.register(glob_tool)
        tool_runner.register(read_tool)
        tool_runner.register(write_tool)
        tool_runner.register(finish_tool)

        # Create conversation with LLM and tool runner
        conversation = Conversation(llm=llm, tool_runner=tool_runner)

        # Generate random question type and get corresponding user prompt
        question_type, user_prompt = get_question_type_prompt()
        print(
            f"Question type: {question_type} ({'existing type' if question_type <= 4 else 'new type'})"
        )
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
                    print(
                        "\nWarning: No question provided with finish. Please provide the question."
                    )
                    finish_tool.reset()
                    continue

                if not files:
                    print(
                        "\nWarning: No files were written. Please write the documents first."
                    )
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
                    raise ValueError(
                        f"Validation failed for written files: {validation_errors}"
                    )

                # Add field labels to documents (must happen before UUID)
                print("\nAdding field labels to documents...")
                label_files(files)

                # Add dataset_doc_uuid to each file and get the UUIDs (always last)
                print("Adding dataset_doc_uuid to documents...")
                document_uuids = add_uuids_to_files(files)

                # Write to generation cache
                write_completeness_entry(question, document_uuids)
                traces_generated += 1
                print(f"\nSaved to {completeness_cache.path}")
                print(f"  Question: {question}")
                print(f"  Document UUIDs: {document_uuids}")
                break

            try:
                if args.auto_accept:
                    user_input = AUTO_CONTINUE_USER_MESSAGE
                    print(f"You (auto): {user_input}")
                else:
                    user_input = input("You: ").strip()
                    if not user_input:
                        continue
                    if user_input.lower() == "quit":
                        print("Exiting early...")
                        quit_requested = True
                        break

                conversation.run_turn(user_input, exit_on_tools=[FINISH_TOOL])

                print()

            except KeyboardInterrupt:
                print("\nExiting early...")
                quit_requested = True
                break

    # Update statistics
    total_traces = count_existing_traces()
    update_statistics(
        "Stage 1: Generate Clean Data",
        "Step 8: Completeness Traces",
        {
            "total_traces": total_traces,
            "traces_generated_this_run": traces_generated,
        },
    )

    print()
    print("=" * 40)
    print(f"Generated {traces_generated} trace(s) this session.")
    print(f"Total traces: {total_traces}")
    print("\nThis step is complete, go on to step 9 to generate volume documents.")


if __name__ == "__main__":
    main()
