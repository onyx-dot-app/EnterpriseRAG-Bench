import json
import os
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from src.llm.interface import LLMInterface, Message, ReasoningLevel, ToolCall
from src.llm.tracing import get_current_span, init_tracing, is_tracing_enabled


LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "gpt-5.4")
CHEAP_LLM_MODEL_NAME = os.environ.get("CHEAP_LLM_MODEL_NAME", "gpt-5-mini")


class OpenAILLM(LLMInterface):
    """OpenAI implementation of the LLM interface using the Responses API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
        quiet: bool = False,
        reasoning_level: ReasoningLevel = "medium",
    ):
        """
        Initialize the OpenAI LLM.

        Args:
            api_key: OpenAI API key. Defaults to LLM_API_KEY env var.
            model: Model to use. Defaults to LLM_MODEL_NAME env var or gpt-5.4.
            tools: List of tool schemas in OpenAI format.
            quiet: If True, suppress status print statements.
            reasoning_level: Level of reasoning effort ("low", "medium", "high").
        """
        self.api_key = api_key or LLM_API_KEY
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set LLM_API_KEY env var or pass api_key."
            )
        self.model = model or LLM_MODEL_NAME
        self.tools = tools
        self.quiet = quiet
        self.reasoning_level = reasoning_level

        # Braintrust's wrap_openai does not support the Responses API
        # streaming format (it assumes Chat Completions objects), causing
        # AttributeError on stream finalization.  Use the raw client and
        # initialise tracing separately so traced_span / log_to_span still work.
        if is_tracing_enabled():
            init_tracing()
        self.client = OpenAI(api_key=self.api_key)

    def _build_input(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert messages to OpenAI Responses API input format."""
        input_items: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                input_items.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                input_items.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                input_items.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool_call" and msg.tool_call:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": msg.tool_call.call_id,
                        "name": msg.tool_call.name,
                        "arguments": json.dumps(msg.tool_call.args),
                    }
                )
            elif msg.role == "tool_result" and msg.call_id:
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.call_id,
                        "output": msg.content,
                    }
                )

        return input_items

    def generate(
        self, messages: list[Message]
    ) -> Generator[str | ToolCall, None, None]:
        """
        Generate a streaming response from OpenAI using the Responses API.

        Args:
            messages: The conversation history.

        Yields:
            String chunks for text responses (prefixed for reasoning),
            or a single ToolCall at the end.
        """
        if not self.quiet:
            print("Waiting on LLM...", flush=True)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": self._build_input(messages),
            "stream": True,
            "reasoning": {"effort": self.reasoning_level, "summary": "auto"},
        }
        if self.tools:
            kwargs["tools"] = self.tools

        stream = self.client.responses.create(**kwargs)

        # Track multiple parallel tool calls
        tool_calls: list[dict[str, str]] = []
        current_tool_call: dict[str, str] | None = None
        in_reasoning = False

        reasoning_content: list[str] = []

        for event in stream:
            event_type = event.type

            # Handle reasoning summary streaming (print directly, don't include in messages)
            if event_type == "response.reasoning_summary_text.delta":
                if not in_reasoning:
                    in_reasoning = True
                    if not self.quiet:
                        print("\n[Reasoning]", flush=True)
                reasoning_content.append(event.delta)
                if not self.quiet:
                    print(event.delta, end="", flush=True)

            elif event_type == "response.reasoning_summary_text.done":
                if in_reasoning:
                    if not self.quiet:
                        print("\n[/Reasoning]\n", flush=True)
                    in_reasoning = False

            # Handle text output streaming
            elif event_type == "response.output_text.delta":
                yield event.delta

            # Handle function/tool calls
            elif event_type == "response.output_item.added":
                item = event.item
                if hasattr(item, "type") and item.type == "function_call":
                    current_tool_call = {
                        "name": item.name,
                        "call_id": item.call_id,
                        "args": "",
                    }
                    if not self.quiet:
                        yield f"\n[Tool Call: {item.name}]\n"

            elif event_type == "response.function_call_arguments.delta":
                if current_tool_call is not None:
                    current_tool_call["args"] += event.delta
                if not self.quiet:
                    yield event.delta

            elif event_type == "response.output_item.done":
                if current_tool_call is not None:
                    if not self.quiet:
                        yield "\n[/Tool Call]\n"
                    tool_calls.append(current_tool_call)
                    current_tool_call = None

        # Log reasoning to Braintrust trace if available
        if reasoning_content:
            span = get_current_span()
            if span:
                span.log(metadata={"reasoning": "".join(reasoning_content)})

        for tc in tool_calls:
            yield ToolCall(
                name=tc["name"],
                args=json.loads(tc["args"]) if tc["args"] else {},
                call_id=tc["call_id"],
            )
