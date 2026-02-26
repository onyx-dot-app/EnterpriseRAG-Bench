"""Automatic conversation utilities for running LLM conversations without user input."""

from src.llm.factory import get_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.tools.runner import ToolRunner


def run_auto_conversation(
    llm: LLMInterface,
    tool_runner: ToolRunner,
    messages: list[Message],
    max_tool_cycles: int = 20,
    max_iterations: int = 50,
    quiet: bool = False,
) -> str:
    """
    Run a conversation automatically without user input until completion.

    Args:
        llm: The LLM instance with tools configured.
        tool_runner: The tool runner with registered tools.
        messages: The conversation messages (modified in place).
        max_tool_cycles: Maximum number of tool call cycles before forcing output.
        max_iterations: Maximum total LLM calls to prevent infinite loops.
        quiet: If True, suppress LLM status output for fallback LLM.

    Returns:
        The final text response from the LLM.

    Raises:
        RuntimeError: If max iterations exceeded without getting a response.
    """
    tool_cycles = 0
    current_llm = llm

    for _ in range(max_iterations):
        full_response = ""
        tool_calls: list[ToolCall] = []

        for chunk in current_llm.generate(messages):
            if isinstance(chunk, str):
                full_response += chunk
            elif isinstance(chunk, ToolCall):
                tool_calls.append(chunk)

        # Handle tool calls
        if tool_calls:
            tool_cycles += 1

            # Check if we've hit the tool cycle limit
            if tool_cycles >= max_tool_cycles:
                # Add a message telling the LLM to output the JSON now
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "You have used the maximum number of tool calls. "
                            "Please output the final result now without any more tool calls."
                        ),
                    )
                )
                # Create a new LLM instance without tools to force text output
                current_llm = get_llm(tools=None, quiet=quiet)
                continue

            for tool_call in tool_calls:
                messages.append(
                    Message(role="tool_call", content="", tool_call=tool_call)
                )
                result = tool_runner.run(tool_call.name, **tool_call.args)
                messages.append(
                    Message(role="tool_result", content=result, call_id=tool_call.call_id)
                )
            continue

        # No tool calls = final response
        if full_response:
            messages.append(Message(role="assistant", content=full_response))
            return full_response

    raise RuntimeError(f"Max iterations ({max_iterations}) exceeded")
