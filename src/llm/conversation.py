from typing import Callable

from src.llm.interface import LLMInterface, Message, ToolCall
from src.llm.tracing import log_to_span, traced_span
from src.tools.runner import ToolRunner
from src.tools.tool_implementations.finish import FinishTool


class Conversation:
    """Maintains a conversation loop with user, agent, and tool calls."""

    def __init__(self, llm: LLMInterface, tool_runner: ToolRunner | None = None):
        self.llm = llm
        self.tool_runner = tool_runner
        self.messages: list[Message] = []
        self._step_count = 0

    def add_system_message(self, content: str) -> None:
        """Add a system message to the conversation."""
        self.messages.append(Message(role="system", content=content))

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
        self.messages.append(
            Message(role="tool_result", content=content, call_id=call_id)
        )

    def generate_response(self, exit_on_tools: list[str] | None = None) -> str:
        """
        Generate a response from the current messages.

        Streams the response to stdout and handles any tool calls.
        When parallel tool calls are made, all are executed before
        returning to the LLM.

        Args:
            exit_on_tools: Optional list of tool names that should cause immediate
                return after being called (without letting LLM generate more text).

        Returns:
            The final assistant response as a string.
        """
        exit_on_tools = exit_on_tools or []

        with traced_span("generate_response", span_type="task") as response_span:
            while True:
                self._step_count += 1
                full_response = ""
                tool_calls: list[ToolCall] = []
                should_exit = False

                with traced_span(
                    f"llm_step_{self._step_count}", span_type="llm"
                ) as step_span:
                    for chunk in self.llm.generate(self.messages):
                        if isinstance(chunk, str):
                            print(chunk, end="", flush=True)
                            full_response += chunk
                        elif isinstance(chunk, ToolCall):
                            tool_calls.append(chunk)

                    log_to_span(
                        step_span,
                        input=[
                            {"role": m.role, "content": m.content[:500]}
                            for m in self.messages[-3:]
                        ],
                        output=full_response if full_response else None,
                        metadata={
                            "tool_calls": (
                                [
                                    {
                                        "name": tc.name,
                                        "args": tc.args,
                                        "call_id": tc.call_id,
                                    }
                                    for tc in tool_calls
                                ]
                                if tool_calls
                                else None
                            ),
                        },
                    )

                # Handle all tool calls before returning to LLM
                if tool_calls:
                    for tool_call in tool_calls:
                        self.add_tool_call(tool_call)

                        if self.tool_runner is None:
                            error_msg = f"Tool '{tool_call.name}' called but no tool runner configured"
                            print(
                                f"\n[Tool Result]\n{error_msg}\n[/Tool Result]\n",
                                flush=True,
                            )
                            self.add_tool_result(tool_call.call_id, error_msg)
                        else:
                            with traced_span(
                                tool_call.name, span_type="tool"
                            ) as tool_span:
                                result = self.tool_runner.run(
                                    tool_call.name, **tool_call.args
                                )
                                log_to_span(
                                    tool_span,
                                    input=tool_call.args,
                                    output=result,
                                )
                            print(
                                f"\n[Tool Result]\n{result}\n[/Tool Result]\n",
                                flush=True,
                            )
                            self.add_tool_result(tool_call.call_id, result)

                        # Check if this tool should cause an early exit
                        if tool_call.name in exit_on_tools:
                            should_exit = True

                    if should_exit:
                        log_to_span(
                            response_span,
                            output=full_response,
                            metadata={"steps": self._step_count},
                        )
                        return full_response

                    continue

                # Return text response only when there are no tool calls
                if full_response:
                    print()  # newline after streaming
                    self.add_assistant_message(full_response)
                    log_to_span(
                        response_span,
                        output=full_response,
                        metadata={"steps": self._step_count},
                    )
                    return full_response

    def run_turn(self, user_input: str, exit_on_tools: list[str] | None = None) -> str:
        """
        Run a single conversation turn.

        Adds the user input, generates a response, and handles any tool calls.
        Streams the response to stdout as it arrives.

        Args:
            user_input: The user's input message.
            exit_on_tools: Optional list of tool names that should cause immediate
                return after being called (without letting LLM generate more text).

        Returns:
            The final assistant response as a string.
        """
        self.add_user_message(user_input)
        return self.generate_response(exit_on_tools=exit_on_tools)

    def run_interactive_loop(
        self,
        finish_tool: FinishTool | None = None,
        on_finish: Callable[[], bool] | None = None,
    ) -> bool:
        """
        Run an interactive conversation loop with user input.

        Handles the common pattern of:
        1. Check if finish_tool was called
        2. Get user input (with quit/keyboard interrupt handling)
        3. Run a conversation turn
        4. Repeat until finished or quit

        Args:
            finish_tool: Optional FinishTool to check for completion signal.
            on_finish: Optional callback when finish_tool signals completion.
                       Should return True to exit the loop, False to continue
                       (e.g., after validation failure and reset).

        Returns:
            True if completed normally (finish_tool or file written),
            False if user quit early.
        """
        while True:
            # Check if finish tool was called
            if finish_tool is not None and finish_tool.finished:
                if on_finish is not None:
                    should_exit = on_finish()
                    if should_exit:
                        return True
                    # on_finish returned False, continue loop (e.g., validation failed)
                    continue
                else:
                    return True

            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() == "quit":
                    print("Goodbye!")
                    return False

                exit_on = [finish_tool.name] if finish_tool is not None else None
                self.run_turn(user_input, exit_on_tools=exit_on)
                print()

            except KeyboardInterrupt:
                print("\nGoodbye!")
                return False
