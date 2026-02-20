"""Interactive script for generating employee directory."""

from datetime import datetime

from src.llm.conversation import Conversation
from src.llm.openai_llm import OpenAILLM
from src.paths import COMPANY_OVERVIEW_PATH, EMPLOYEE_DIRECTORY_PATH, INITIATIVES_PATH
from src.prompts.employee_directory import EMPLOYEE_DIRECTORY_SYSTEM_PROMPT
from src.schemas.employee_directory import EXPECTED_FORMAT, validate_employee_directory
from src.tools.runner import ToolRunner
from src.tools.write import WriteTool


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
    initiatives = load_file(INITIATIVES_PATH)
    current_date = datetime.now().strftime("%B %d, %Y")

    prompt = EMPLOYEE_DIRECTORY_SYSTEM_PROMPT.format(
        company_overview_md_contents=company_overview,
        initiatives_md_contents=initiatives,
        current_date=current_date,
    )

    # Create write tool with validation for employee directory schema
    write_tool = WriteTool(
        file_path_override=EMPLOYEE_DIRECTORY_PATH,
        validator=validate_employee_directory,
        expected_format=EXPECTED_FORMAT,
    )

    # Initialize LLM with write tool schema
    llm = OpenAILLM(tools=[write_tool.schema])

    # Create tool runner and register the write tool
    tool_runner = ToolRunner()
    tool_runner.register(write_tool)

    # Create conversation with LLM and tool runner
    conversation = Conversation(llm=llm, tool_runner=tool_runner)

    print("Employee Directory Generator")
    print("=" * 40)
    print("Collaborate with the assistant to generate the employee directory.")
    print("Type 'quit' to exit.\n")

    # Get initial response from the assistant using system prompt
    conversation.run_turn(prompt)
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
