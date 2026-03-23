"""Interactive script for generating company overviews."""

import os

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import COMPANY_OVERVIEW_PATH
from src.prompts.company_overview import COMPANY_OVERVIEW_SYSTEM_PROMPT
from src.utils.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import WriteTool
from src.tools.tool_implementations.finish import FinishTool
from src.utils import confirm_regenerate


def main() -> None:
    # Check if company overview already exists
    if os.path.exists(COMPANY_OVERVIEW_PATH):
        if not confirm_regenerate("Company overview"):
            print("Updating statistics only...")
            update_statistics("Stage 1: Generate Clean Data", "Step 1: Company Overview", {
                "status": f"Completed - see file at {COMPANY_OVERVIEW_PATH}",
            })
            print("Statistics updated.")
            return

    # Create write tool with override to company_overview.md
    write_tool = WriteTool(file_path_override=COMPANY_OVERVIEW_PATH)
    finish_tool = FinishTool()

    # Initialize LLM with write tool schema
    llm = get_llm(tools=[write_tool.schema, finish_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)
    tool_runner.register(finish_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Step 1: Company Overview Generator")
    print("=" * 40)
    print("This script generates a company overview document that serves as the foundation")
    print("for all subsequent data generation steps.")
    print()
    print("You will have a conversation with an LLM to guide you through the process.")
    input("Press Enter to begin...")
    print()
    print("Type 'quit' to exit.\n")

    # Add system prompt and get initial response
    conversation.add_system_message(COMPANY_OVERVIEW_SYSTEM_PROMPT)
    conversation.generate_response()
    print()

    # Interactive loop
    completed = conversation.run_interactive_loop(finish_tool=finish_tool)
    if completed:
        print("\nNext step: run step_2_generate_initiatives.py")

    # Update statistics if file was created
    if os.path.exists(COMPANY_OVERVIEW_PATH):
        update_statistics("Stage 1: Generate Clean Data", "Step 1: Company Overview", {
            "status": f"Completed - see file at {COMPANY_OVERVIEW_PATH}",
        })


if __name__ == "__main__":
    main()
