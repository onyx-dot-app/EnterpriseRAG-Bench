"""Interactive script for generating company initiatives and roadmap."""

import os

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import COMPANY_OVERVIEW_PATH, INITIATIVES_PATH
from src.prompts.initiatives import INITIATIVES_SYSTEM_PROMPT
from src.utils.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import WriteTool
from src.tools.tool_implementations.finish import FinishTool
from src.utils import confirm_regenerate, get_current_date_formatted, load_file


def main() -> None:
    # Check if initiatives already exists
    if os.path.exists(INITIATIVES_PATH):
        if not confirm_regenerate("Initiatives"):
            print("Updating statistics only...")
            update_statistics(
                "Stage 1: Generate Clean Data",
                "Step 2: Initiatives",
                {
                    "status": f"Completed - see file at {INITIATIVES_PATH}",
                },
            )
            print("Statistics updated.")
            return

    # Load company overview and build the prompt
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    prompt = INITIATIVES_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        current_date=get_current_date_formatted(),
    )

    # Create write tool with override to initiatives.md
    write_tool = WriteTool(file_path_override=INITIATIVES_PATH)
    finish_tool = FinishTool()

    # Initialize LLM with write tool schema
    llm = get_llm(tools=[write_tool.schema, finish_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)
    tool_runner.register(finish_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Step 2: Initiatives & Roadmap Generator")
    print("=" * 40)
    print(
        "This script generates company initiatives and roadmap based on the company overview."
    )
    print(
        "These initiatives will inform the content and context of generated documents."
    )
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
    completed = conversation.run_interactive_loop(finish_tool=finish_tool)
    if completed:
        print("\nNext step: run step_3_generate_employee_directory.py")

    # Update statistics if file was created
    if os.path.exists(INITIATIVES_PATH):
        update_statistics(
            "Stage 1: Generate Clean Data",
            "Step 2: Initiatives",
            {
                "status": f"Completed - see file at {INITIATIVES_PATH}",
            },
        )


if __name__ == "__main__":
    main()
