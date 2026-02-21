"""Interactive script for generating source directory structure."""

import subprocess
from datetime import datetime

from src.llm.conversation import Conversation
from src.llm.openai_llm import OpenAILLM
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


def load_file(path: str) -> str:
    """Load a file and return its contents."""
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


def write_source_tree() -> None:
    """Write the source directory tree to a file."""
    print("\n" + "=" * 40)
    print("Writing Source Directory Tree")
    print("=" * 40)

    # Run tree command on sources directory (directories only)
    result = subprocess.run(
        ["tree", "-d", SOURCES_DIR],
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


def main() -> None:
    # Load context files and build the prompt
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    initiatives = load_file(INITIATIVES_PATH)
    current_date = datetime.now().strftime("%B %d, %Y")

    prompt = SOURCE_STRUCTURE_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        initiatives_md_contents=initiatives,
        current_date=current_date,
    )

    # Create tools
    mkdir_tool = MkdirTool(base_dir=SOURCES_DIR)
    rmdir_tool = RmdirTool(base_dir=SOURCES_DIR)
    mvdir_tool = MvdirTool(base_dir=SOURCES_DIR)
    tree_tool = TreeTool(base_dir=SOURCES_DIR)
    filter_llm = OpenAILLM()  # LLM for filtering employee directory queries
    read_employee_directory_tool = ReadEmployeeDirectoryTool(llm=filter_llm)
    finish_tool = FinishTool()

    # Initialize main LLM with tool schemas
    llm = OpenAILLM(tools=[
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

    # Interactive loop
    while True:
        # Check if finish tool was called
        if finish_tool.finished:
            write_source_tree()
            print("\nSource directory structure generation complete!")
            break

        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Goodbye!")
                break

            conversation.run_turn(user_input)
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
