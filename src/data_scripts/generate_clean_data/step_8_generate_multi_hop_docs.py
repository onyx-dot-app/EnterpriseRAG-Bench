"""Interactive script for generating multi-hop document chains."""

import json
import os

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    MULTI_HOP_DIR,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.multi_hop import MULTI_HOP_SYSTEM_PROMPT
from src.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, GlobTool, ReadTool, RmTool, WriteTool
from src.utils import delete_file, load_file, load_json_file, validate_no_nested_dicts, write_json_file


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
    """Count existing multi-hop trace files."""
    if not os.path.exists(MULTI_HOP_DIR):
        return 0
    return len([f for f in os.listdir(MULTI_HOP_DIR) if f.startswith("multi_hop_trace_") and f.endswith(".json")])


def get_next_trace_number() -> int:
    """Get the next available trace number."""
    if not os.path.exists(MULTI_HOP_DIR):
        return 1
    existing = [
        f for f in os.listdir(MULTI_HOP_DIR)
        if f.startswith("multi_hop_trace_") and f.endswith(".json")
    ]
    if not existing:
        return 1
    numbers = []
    for f in existing:
        try:
            num = int(f.replace("multi_hop_trace_", "").replace(".json", ""))
            numbers.append(num)
        except ValueError:
            pass
    return max(numbers) + 1 if numbers else 1


def write_trace(trace_number: int, question: str, files: list[str]) -> str:
    """Write a multi-hop trace JSON file."""
    trace_path = os.path.join(MULTI_HOP_DIR, f"multi_hop_trace_{trace_number}.json")
    trace_data = {
        "question": question,
        "files": files,
    }
    write_json_file(trace_path, trace_data)
    return trace_path


def main() -> None:
    # Show existing traces and prompt for count
    existing_count = count_existing_traces()
    print("Step 8: Multi-Hop Document Chain Generator (Optional Step)")
    print("=" * 40)
    print("This script generates multi-hop document chains for complex questions.")
    print("Each chain consists of documents that reference each other.")
    print()
    print("Note that this is a difficult task and the LLM may fail to follow all instructions every time. Use a strong LLM for this.")
    print()
    print(f"Existing multi-hop traces: {existing_count}")
    print()

    # Prompt for number of traces to generate
    while True:
        try:
            num_to_generate = input("How many multi-hop traces would you like to generate? ").strip()
            num_to_generate = int(num_to_generate)
            if num_to_generate <= 0:
                print("Please enter a positive number.")
                continue
            break
        except ValueError:
            print("Please enter a valid number.")
            continue

    print()
    print(f"Will generate {num_to_generate} multi-hop trace(s).")
    print("Type 'quit' at any prompt to exit early.\n")

    # Load context files
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    source_tree = load_file(SOURCE_TREE_PATH)

    prompt = MULTI_HOP_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        source_tree_contents=source_tree,
    )

    traces_generated = 0
    quit_requested = False

    for i in range(num_to_generate):
        if quit_requested:
            break

        trace_number = get_next_trace_number()

        # Retry loop for validation failures
        while True:
            print()
            print("=" * 40)
            print(f"Generating trace {i + 1} of {num_to_generate} (will be saved as multi_hop_trace_{trace_number}.json)")
            print("=" * 40)
            print()

            # Create fresh tools for this attempt
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

            # Add system prompt and get initial response
            conversation.add_system_message(prompt)
            conversation.generate_response()
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
                            print(f"  ✗ {error}")
                        print()
                        print("Deleting all files from this step...")
                        delete_written_files(files)
                        print()
                        print("Automatically retrying with a fresh conversation...")
                        print("=" * 40)
                        break

                    # Write the trace
                    trace_path = write_trace(trace_number, question, files)
                    traces_generated += 1
                    print(f"\n✓ Saved trace to {trace_path}")
                    print(f"  Question: {question}")
                    print(f"  Files: {files}")
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

            # Exit retry loop if trace is complete or quit requested
            if trace_complete or quit_requested:
                break
            # Otherwise retry_needed is True, loop continues with fresh conversation

    # Update statistics
    total_traces = count_existing_traces()
    update_statistics("Step 8: Multi-Hop Traces", {
        "total_traces": total_traces,
        "traces_generated_this_run": traces_generated,
    })

    print()
    print("=" * 40)
    print("Multi-hop generation complete!")
    print(f"Generated {traces_generated} trace(s) this session.")
    print(f"Total traces: {total_traces}")


if __name__ == "__main__":
    main()
