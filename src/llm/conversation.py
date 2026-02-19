from src.llm.interface import LLMInterface, Message, ToolCall
from src.tools.runner import ToolRunner


class Conversation:
    """Maintains a conversation loop with user, agent, and tool calls."""

    def __init__(self, llm: LLMInterface, tool_runner: ToolRunner | None = None):
        self.llm = llm
        self.tool_runner = tool_runner
        self.messages: list[Message] = []

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self.messages.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the conversation."""
        self.messages.append(Message(role="assistant", content=content))

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the conversation."""
        self.messages.append(Message(role="tool_call", content="", tool_call=tool_call))

    def add_tool_result(self, call_id: str, content: str) -> None:
        """Add a tool result to the conversation."""
        self.messages.append(Message(role="tool_result", content=content, call_id=call_id))

    def run_turn(self, user_input: str) -> str:
        """
        Run a single conversation turn.

        Adds the user input, generates a response, and handles any tool calls.
        Streams the response to stdout as it arrives.

        Args:
            user_input: The user's input message.

        Returns:
            The final assistant response as a string.
        """
        self.add_user_message(user_input)

        while True:
            full_response = ""
            tool_call: ToolCall | None = None

            for chunk in self.llm.generate(self.messages):
                if isinstance(chunk, str):
                    print(chunk, end="", flush=True)
                    full_response += chunk
                elif isinstance(chunk, ToolCall):
                    tool_call = chunk

            # Handle tool call first - execute and continue loop for LLM to process result
            if tool_call:
                self.add_tool_call(tool_call)

                if self.tool_runner is None:
                    error_msg = f"Tool '{tool_call.name}' called but no tool runner configured"
                    print(f"\n[Tool Result]\n{error_msg}\n[/Tool Result]\n", flush=True)
                    self.add_tool_result(tool_call.call_id, error_msg)
                else:
                    result = self.tool_runner.run(tool_call.name, **tool_call.args)
                    print(f"\n[Tool Result]\n{result}\n[/Tool Result]\n", flush=True)
                    self.add_tool_result(tool_call.call_id, result)
                continue

            # Return text response only when there's no tool call
            if full_response:
                print()  # newline after streaming
                self.add_assistant_message(full_response)
                return full_response
