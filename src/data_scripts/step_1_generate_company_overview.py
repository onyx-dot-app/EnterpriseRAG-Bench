"""Interactive script for generating company overviews."""

from src.llm.conversation import Conversation
from src.llm.openai_llm import OpenAILLM
from src.paths import COMPANY_OVERVIEW_PATH
from src.prompts.company_overview import COMPANY_OVERVIEW_SYSTEM_PROMPT
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import WriteTool


def main() -> None:
    # Create write tool with override to company_overview.md
    write_tool = WriteTool(file_path_override=COMPANY_OVERVIEW_PATH)

    # Initialize LLM with write tool schema
    llm = OpenAILLM(tools=[write_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Company Overview Generator")
    print("=" * 40)
    print("Collaborate with the assistant to generate a company overview.")
    print("Type 'quit' to exit.\n")

    # Add system prompt and get initial response
    conversation.add_system_message(COMPANY_OVERVIEW_SYSTEM_PROMPT)
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
