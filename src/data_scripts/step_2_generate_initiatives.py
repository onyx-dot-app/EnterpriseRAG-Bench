"""Interactive script for generating company initiatives and roadmap."""

from datetime import datetime

from src.llm.conversation import Conversation
from src.llm.openai_llm import OpenAILLM
from src.paths import COMPANY_OVERVIEW_PATH, INITIATIVES_PATH
from src.prompts.initiatives import INITIATIVES_SYSTEM_PROMPT
from src.tools.runner import ToolRunner
from src.tools.write import WriteTool


def load_company_overview() -> str:
    """Load the company overview markdown file."""
    with open(COMPANY_OVERVIEW_PATH) as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"Company overview at {COMPANY_OVERVIEW_PATH} is empty")
    return content


def main() -> None:
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
    llm = OpenAILLM(tools=[write_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Initiatives & Roadmap Generator")
    print("=" * 40)
    print("Collaborate with the assistant to generate company initiatives.")
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


if __name__ == "__main__":
    main()
