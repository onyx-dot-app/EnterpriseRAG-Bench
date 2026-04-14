"""Interactive script for generating agents.md files in source directories.

Creates agents.md files throughout the source directory tree to guide the format and
content of documents generated within each source type. For example, a GitHub agents.md
might specify that all documents represent pull-requests with comments. These files are
pulled into downstream document generation prompts.

Usage:
    python -m src.scripts.data_gen_stage_1_generate_clean_data.step_5_generate_agents_md

No arguments. The script is fully interactive.
"""

import os

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.agents_md import AGENTS_MD_SYSTEM_PROMPT
from src.utils.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, WriteTool
from src.utils import confirm_yes_no, load_file

STEP_OVERVIEW = """\
Generates agents.md files in source directories to guide the format and content
of documents within each source type. For example, GitHub's agents.md might
specify all documents represent pull-requests with comments.

NOTE: You can generate as many agents.md files as you would like. The important
      piece is that the top level directories all have one, but additional ones
      are at your discretion.

TIP:  You are encouraged to manually modify the generated agents.md files to
      best represent what you want in there.

You will have a conversation with an LLM to guide you through the process.
Type 'quit' to exit.
"""


def find_agents_md_files(base_dir: str) -> list[str]:
    """
    Find all agents.md files and return their relative paths.

    Args:
        base_dir: Base directory to search in.

    Returns:
        Sorted list of relative paths to agents.md files.
    """
    paths = []
    for root, _dirs, files in os.walk(base_dir):
        if AGENTS_MD_FILE in files:
            rel_path = os.path.relpath(os.path.join(root, AGENTS_MD_FILE), base_dir)
            paths.append(rel_path)
    return sorted(paths)


def _has_agents_md_files() -> bool:
    """Check if there are any agents.md files under sources."""
    return len(find_agents_md_files(SOURCES_DIR)) > 0


def _confirm_generate_more() -> bool:
    """Prompt user to confirm generating more agents.md files."""
    return confirm_yes_no(
        "agents.md files already exist. Generate more?", default=False
    )


def main() -> None:
    # Check if agents.md files already exist
    if _has_agents_md_files():
        if not _confirm_generate_more():
            # Just update statistics and exit
            print("Updating statistics only...")
            agents_paths = find_agents_md_files(SOURCES_DIR)
            update_statistics(
                "Stage 1: Generate Clean Data",
                "Step 5: Agents MD",
                {
                    "total_agents_md_files": len(agents_paths),
                    "paths": agents_paths,
                },
            )
            print("Statistics updated.")
            return

    # Load context files and build the prompt
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    source_tree = load_file(SOURCE_TREE_PATH)

    prompt = AGENTS_MD_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        sources_dir_tree=source_tree,
    )

    # Create tools (allow_create_dirs=False prevents creating new directories)
    write_tool = WriteTool(base_dir=SOURCES_DIR, allow_create_dirs=False)
    finish_tool = FinishTool()

    # Initialize main LLM with tool schemas
    llm = get_llm(
        tools=[
            write_tool.schema,
            finish_tool.schema,
        ]
    )

    # Create tool runner and register tools
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)
    tool_runner.register(finish_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print(f"Step 5: {AGENTS_MD_FILE} Generator")
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
        # Update aggregate statistics
        agents_paths = find_agents_md_files(SOURCES_DIR)
        update_statistics(
            "Stage 1: Generate Clean Data",
            "Step 5: Agents MD",
            {
                "total_agents_md_files": len(agents_paths),
                "paths": agents_paths,
            },
        )
        print("\nThis step is complete, go on to step 6 to generate projects.")
        return True

    # Interactive loop
    conversation.run_interactive_loop(finish_tool=finish_tool, on_finish=on_finish)


if __name__ == "__main__":
    main()
