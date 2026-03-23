"""Automatic conversation utilities for running LLM conversations without user input."""

from src.llm.factory import get_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.llm.tracing import log_to_span, traced_span
from src.tools.exceptions import ToolTerminationSignal
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
    with traced_span("auto_conversation", span_type="task") as conversation_span:
        tool_cycles = 0
        current_llm = llm
        step = 0

        for _ in range(max_iterations):
            step += 1
            full_response = ""
            tool_calls: list[ToolCall] = []

            with traced_span(f"llm_step_{step}", span_type="llm") as step_span:
                for chunk in current_llm.generate(messages):
                    if isinstance(chunk, str):
                        full_response += chunk
                    elif isinstance(chunk, ToolCall):
                        tool_calls.append(chunk)

                # Log LLM output to span
                log_to_span(
                    step_span,
                    input=[
                        {"role": m.role, "content": m.content[:500]}
                        for m in messages[-3:]
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

                    termination_signal: ToolTerminationSignal | None = None

                    with traced_span(tool_call.name, span_type="tool") as tool_span:
                        try:
                            result = tool_runner.run(tool_call.name, **tool_call.args)
                        except ToolTerminationSignal as sig:
                            # Capture signal but don't propagate through context manager
                            result = sig.result
                            termination_signal = sig
                        log_to_span(
                            tool_span,
                            input=tool_call.args,
                            output=result,
                        )

                    messages.append(
                        Message(
                            role="tool_result",
                            content=result,
                            call_id=tool_call.call_id,
                        )
                    )

                    if termination_signal is not None:
                        log_to_span(
                            conversation_span,
                            output=result,
                            metadata={
                                "total_steps": step,
                                "tool_cycles": tool_cycles,
                                "terminated_by_tool": True,
                            },
                        )
                        return result
                continue

            # No tool calls = final response
            if full_response:
                messages.append(Message(role="assistant", content=full_response))
                log_to_span(
                    conversation_span,
                    output=full_response,
                    metadata={"total_steps": step, "tool_cycles": tool_cycles},
                )
                return full_response

        raise RuntimeError(f"Max iterations ({max_iterations}) exceeded")
