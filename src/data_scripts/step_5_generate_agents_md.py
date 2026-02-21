"""Interactive script for generating agents.md files in source directories."""

from src.llm.conversation import Conversation
from src.llm.openai_llm import OpenAILLM
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    SOURCE_TREE_PATH,
    SOURCES_DIR,
)
from src.prompts.agents_md import AGENTS_MD_SYSTEM_PROMPT
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, WriteTool


def load_file(path: str) -> str:
    """Load a file and return its contents."""
    with open(path) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"File at {path} is empty")
    return content


def main() -> None:
    # Load context files and build the prompt
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    source_tree = load_file(SOURCE_TREE_PATH)

    prompt = AGENTS_MD_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        sources_dir_tree=source_tree,
    )

    # Create tools
    write_tool = WriteTool(base_dir=SOURCES_DIR)
    finish_tool = FinishTool()

    # Initialize main LLM with tool schemas
    llm = OpenAILLM(tools=[
        write_tool.schema,
        finish_tool.schema,
    ])

    # Create tool runner and register tools
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)
    tool_runner.register(finish_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print(f"Step 5: {AGENTS_MD_FILE} Generator")
    print("=" * 40)
    print(f"This script creates {AGENTS_MD_FILE} files that guide document generation for each directory.")
    print("These files define content rules, metadata rules, and target document counts.")
    print(f"Base directory: {SOURCES_DIR}")
    print()
    print(f"NOTE: You can generate as many {AGENTS_MD_FILE} files as you would like.")
    print(f"      The relatively important piece is that the top level directories")
    print(f"      all have an {AGENTS_MD_FILE} file but additional ones are at your discretion.")
    print()
    print(f"TIP:  You are encouraged to manually modify the generated {AGENTS_MD_FILE} files")
    print(f"      to best represent what you want in there.")
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
            print(f"\n{AGENTS_MD_FILE} generation complete!")
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
