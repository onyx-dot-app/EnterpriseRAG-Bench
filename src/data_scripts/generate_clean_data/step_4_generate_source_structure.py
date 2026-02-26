"""Interactive script for generating source directory structure."""

import os
import subprocess

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    DATA_CLEAN_DIR,
    INITIATIVES_PATH,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.source_structure import SOURCE_STRUCTURE_SYSTEM_PROMPT
from src.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    FinishTool,
    MkdirTool,
    MvdirTool,
    ReadEmployeeDirectoryTool,
    RmdirTool,
    TreeTool,
)
from src.utils import confirm_regenerate, get_current_date_formatted, load_file


def count_directories(base_dir: str) -> tuple[int, int]:
    """
    Count top-level and total nested directories.

    Returns:
        (top_level_count, total_count)
    """
    top_level = 0
    total = 0
    for root, dirs, _files in os.walk(base_dir):
        if root == base_dir:
            top_level = len(dirs)
        total += len(dirs)
    return top_level, total


def write_source_tree() -> None:
    """Write the source directory tree to a file."""
    print("\n" + "=" * 40)
    print("Writing Source Directory Tree")
    print("=" * 40)

    # Run tree command from data_clean dir with just "sources" as argument
    # This outputs "sources" as the root instead of "data_clean/sources"
    result = subprocess.run(
        ["tree", "-d", "sources"],
        cwd=DATA_CLEAN_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error running tree command: {result.stderr}")
        return

    tree_output = result.stdout

    # Write to file
    with open(SOURCE_TREE_PATH, "w") as f:
        f.write(tree_output)

    print(tree_output)
    print()
    print(f"✓ Saved source directory tree to {SOURCE_TREE_PATH}")


def _has_source_directories() -> bool:
    """Check if there are any directories under sources."""
    if not os.path.exists(SOURCES_DIR):
        return False
    entries = os.listdir(SOURCES_DIR)
    return any(os.path.isdir(os.path.join(SOURCES_DIR, e)) for e in entries)


def main() -> None:
    # Check if source directories already exist
    if _has_source_directories():
        if not confirm_regenerate("Source directories"):
            # Regenerate source_tree.txt and update statistics
            write_source_tree()
            top_level, total = count_directories(SOURCES_DIR)
            update_statistics("Step 4: Source Structure", {
                "top_level_directories": top_level,
                "total_directories": total,
            })
            print("Statistics updated.")
            return

    # Load context files and build the prompt
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    initiatives = load_file(INITIATIVES_PATH)

    prompt = SOURCE_STRUCTURE_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        initiatives_md_contents=initiatives,
        current_date=get_current_date_formatted(),
    )

    # Create tools
    mkdir_tool = MkdirTool(base_dir=SOURCES_DIR)
    rmdir_tool = RmdirTool(base_dir=SOURCES_DIR)
    mvdir_tool = MvdirTool(base_dir=SOURCES_DIR)
    tree_tool = TreeTool(base_dir=SOURCES_DIR)
    filter_llm = get_llm()  # LLM for filtering employee directory queries
    read_employee_directory_tool = ReadEmployeeDirectoryTool(llm=filter_llm)
    finish_tool = FinishTool()

    # Initialize main LLM with tool schemas
    llm = get_llm(tools=[
        mkdir_tool.schema,
        rmdir_tool.schema,
        mvdir_tool.schema,
        tree_tool.schema,
        read_employee_directory_tool.schema,
        finish_tool.schema,
    ])

    # Create tool runner and register tools
    tool_runner = ToolRunner()
    tool_runner.register(mkdir_tool)
    tool_runner.register(rmdir_tool)
    tool_runner.register(mvdir_tool)
    tool_runner.register(tree_tool)
    tool_runner.register(read_employee_directory_tool)
    tool_runner.register(finish_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Step 4: Source Directory Structure Generator")
    print("=" * 40)
    print("This script creates the directory structure for data sources (Slack, GitHub, etc.).")
    print("These directories will be populated with documents in later steps.")
    print(f"Base directory: {SOURCES_DIR}")
    print()
    print("TIP: This step is best run in batches (e.g., one source type at a time).")
    print("     Long conversations cost more per turn as context accumulates.")
    print("     You can quit and re-run to start fresh while keeping created directories.")
    print()
    print("You will have a conversation with an LLM to guide you through the process.")
    input("Press Enter to begin...")
    print()
    print("Type 'quit' to exit.\n")

    # Add system prompt and get initial response
    conversation.add_system_message(prompt)
    conversation.generate_response()
    print()

    def on_finish() -> bool:
        """Handle finish signal."""
        write_source_tree()
        # Update aggregate statistics
        top_level, total = count_directories(SOURCES_DIR)
        update_statistics("Step 4: Source Structure", {
            "top_level_directories": top_level,
            "total_directories": total,
        })
        print("\nSource directory structure generation complete!")
        return True

    # Interactive loop
    conversation.run_interactive_loop(finish_tool=finish_tool, on_finish=on_finish)


if __name__ == "__main__":
    main()
