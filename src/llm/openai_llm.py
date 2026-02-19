import json
import os
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from src.llm.interface import LLMInterface, Message, ToolCall


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


class OpenAILLM(LLMInterface):
    """OpenAI implementation of the LLM interface using the Responses API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
    ):
        """
        Initialize the OpenAI LLM.

        Args:
            api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
            model: Model to use. Defaults to LLM_MODEL env var or gpt-4o-mini.
            tools: List of tool schemas in OpenAI format.
        """
        self.api_key = api_key or OPENAI_API_KEY
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key."
            )
        self.model = model or LLM_MODEL
        self.tools = tools
        self.client = OpenAI(api_key=self.api_key)

    def _build_input(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert messages to OpenAI Responses API input format."""
        input_items: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "user":
                input_items.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                input_items.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool_call" and msg.tool_call:
                input_items.append({
                    "type": "function_call",
                    "call_id": msg.tool_call.call_id,
                    "name": msg.tool_call.name,
                    "arguments": json.dumps(msg.tool_call.args),
                })
            elif msg.role == "tool_result" and msg.call_id:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": msg.call_id,
                    "output": msg.content,
                })

        return input_items

    def generate(self, messages: list[Message]) -> Generator[str | ToolCall, None, None]:
        """
        Generate a streaming response from OpenAI using the Responses API.

        Args:
            messages: The conversation history.

        Yields:
            String chunks for text responses (prefixed for reasoning),
            or a single ToolCall at the end.
        """
        print("Waiting on LLM...", flush=True)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": self._build_input(messages),
            "stream": True,
        }
        if self.tools:
            kwargs["tools"] = self.tools

        stream = self.client.responses.create(**kwargs)

        tool_call_id = ""
        tool_call_name = ""
        tool_call_args = ""
        in_reasoning = False
        in_tool_call = False

        for event in stream:
            event_type = event.type

            # Handle reasoning summary streaming
            if event_type == "response.reasoning_summary_text.delta":
                if not in_reasoning:
                    in_reasoning = True
                    yield "\n[Reasoning]\n"
                yield event.delta

            elif event_type == "response.reasoning_summary_text.done":
                if in_reasoning:
                    yield "\n[/Reasoning]\n\n"
                    in_reasoning = False

            # Handle text output streaming
            elif event_type == "response.output_text.delta":
                yield event.delta

            # Handle function/tool calls
            elif event_type == "response.output_item.added":
                item = event.item
                if hasattr(item, "type") and item.type == "function_call":
                    tool_call_name = item.name
                    tool_call_id = item.call_id
                    in_tool_call = True
                    yield f"\n[Tool Call: {tool_call_name}]\n"

            elif event_type == "response.function_call_arguments.delta":
                tool_call_args += event.delta
                yield event.delta

            elif event_type == "response.output_item.done":
                if in_tool_call:
                    yield "\n[/Tool Call]\n"
                    in_tool_call = False

        if tool_call_name:
            yield ToolCall(
                name=tool_call_name,
                args=json.loads(tool_call_args) if tool_call_args else {},
                call_id=tool_call_id,
            )
