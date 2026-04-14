"""Interactive script for generating the source directory structure.

Creates the nested directory hierarchy under generated_data/sources/ (e.g. slack/,
confluence/, github/) through an interactive LLM conversation. The user specifies
which source types to include and their internal folder layout. Outputs a source_tree.txt
for reference in later steps.

Usage:
    python -m src.scripts.data_gen_stage_1_generate_clean_data.step_4_generate_source_structure

No arguments. The script is fully interactive.
"""

import os

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    INITIATIVES_PATH,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.source_structure import SOURCE_STRUCTURE_SYSTEM_PROMPT
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import (
    FinishTool,
    MkdirTool,
    MvdirTool,
    ReadEmployeeDirectoryTool,
    RmdirTool,
    TreeTool,
)
from src.utils import (
    confirm_regenerate,
    get_current_date_formatted,
    get_directory_tree,
    load_file,
)
from src.utils.statistics import update_statistics

STEP_OVERVIEW = """\
Creates the nested directory hierarchy under sources/ (e.g. slack/, confluence/,
github/) through an interactive LLM conversation. Takes into account the company
overview, initiatives, and employee directory.

TIP: This step is best run in batches (e.g. one source type at a time).
     Long conversations cost more per turn as context accumulates.
     You can quit and re-run to start fresh while keeping created directories.

You will have a conversation with an LLM to guide you through the process.
Type 'quit' to exit.
"""


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

    tree_output = get_directory_tree(SOURCES_DIR)

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
            update_statistics(
                "Stage 1: Generate Clean Data",
                "Step 4: Source Structure",
                {
                    "top_level_directories": top_level,
                    "total_directories": total,
                },
            )
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
    llm = get_llm(
        tools=[
            mkdir_tool.schema,
            rmdir_tool.schema,
            mvdir_tool.schema,
            tree_tool.schema,
            read_employee_directory_tool.schema,
            finish_tool.schema,
        ]
    )

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
    print(STEP_OVERVIEW)
    print(f"Base directory: {SOURCES_DIR}")
    input("\nPress Enter to begin...")

    # Add system prompt and get initial response
    conversation.add_system_message(prompt)
    conversation.generate_response()
    print()

    def on_finish() -> bool:
        """Handle finish signal."""
        write_source_tree()
        # Update aggregate statistics
        top_level, total = count_directories(SOURCES_DIR)
        update_statistics(
            "Stage 1: Generate Clean Data",
            "Step 4: Source Structure",
            {
                "top_level_directories": top_level,
                "total_directories": total,
            },
        )
        print("\nThis step is complete, go on to step 5 to generate agents.md files.")
        return True

    # Interactive loop
    conversation.run_interactive_loop(finish_tool=finish_tool, on_finish=on_finish)


if __name__ == "__main__":
    main()
