"""Interactive script for generating company initiatives and roadmap."""

import os
from datetime import datetime

from src.llm import get_llm
from src.llm.conversation import Conversation
from src.paths import COMPANY_OVERVIEW_PATH, INITIATIVES_PATH
from src.prompts.initiatives import INITIATIVES_SYSTEM_PROMPT
from src.statistics import update_statistics
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import WriteTool


def _confirm_regenerate(data_description: str) -> bool:
    """Prompt user to confirm regeneration of existing data."""
    response = input(f"{data_description} already exists. Regenerate? [y/N]: ").strip().lower()
    return response in ("y", "yes")


def load_company_overview() -> str:
    """Load the company overview markdown file."""
    with open(COMPANY_OVERVIEW_PATH) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"Company overview at {COMPANY_OVERVIEW_PATH} is empty")
    return content


def main() -> None:
    # Check if initiatives already exists
    if os.path.exists(INITIATIVES_PATH):
        if not _confirm_regenerate("Initiatives"):
            print("Updating statistics only...")
            update_statistics("Step 2: Initiatives", {
                "status": f"Completed - see file at {INITIATIVES_PATH}",
            })
            print("Statistics updated.")
            return

    # Load company overview and build the prompt
    company_overview = load_company_overview()
    current_date = datetime.now().strftime("%B %d, %Y")
    prompt = INITIATIVES_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        current_date=current_date,
    )

    # Create write tool with override to initiatives.md
    write_tool = WriteTool(file_path_override=INITIATIVES_PATH)

    # Initialize LLM with write tool schema
    llm = get_llm(tools=[write_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Step 2: Initiatives & Roadmap Generator")
    print("=" * 40)
    print("This script generates company initiatives and roadmap based on the company overview.")
    print("These initiatives will inform the content and context of generated documents.")
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

    # Update statistics if file was created
    if os.path.exists(INITIATIVES_PATH):
        update_statistics("Step 2: Initiatives", {
            "status": f"Completed - see file at {INITIATIVES_PATH}",
        })


if __name__ == "__main__":
    main()
