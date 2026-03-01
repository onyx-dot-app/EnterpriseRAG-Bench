import json
import os
from collections.abc import Generator
from typing import Any

import anthropic

from src.llm.interface import LLMInterface, Message, ReasoningLevel, ToolCall


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
BRAINTRUST_API_KEY = os.environ.get("BRAINTRUST_API_KEY")
BRAINTRUST_PROJECT = os.environ.get("BRAINTRUST_PROJECT")


def _init_braintrust_client(api_key: str) -> anthropic.Anthropic:
    """Initialize Anthropic client with Braintrust tracing."""
    from braintrust import init_logger, wrap_anthropic

    init_logger(project=BRAINTRUST_PROJECT)
    return wrap_anthropic(anthropic.Anthropic(api_key=api_key))


class AnthropicLLM(LLMInterface):
    """Anthropic implementation of the LLM interface."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
        quiet: bool = False,
        reasoning_level: ReasoningLevel = "medium",
    ):
        """
        Initialize the Anthropic LLM.

        Args:
            api_key: Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
            model: Model to use. Defaults to ANTHROPIC_MODEL env var or claude-sonnet-4-20250514.
            tools: List of tool schemas in OpenAI format (will be converted).
            quiet: If True, suppress status print statements.
            reasoning_level: Level of reasoning effort ("low", "medium", "high").
        """
        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )
        self.model = model or ANTHROPIC_MODEL
        self.tools = self._convert_tools(tools) if tools else None
        self.quiet = quiet
        self.reasoning_level = reasoning_level

        # Use Braintrust tracing if configured
        if BRAINTRUST_API_KEY and BRAINTRUST_PROJECT:
            self.client = _init_braintrust_client(self.api_key)
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    def _convert_tools(self, openai_tools: list[dict]) -> list[dict]:
        """Convert OpenAI tool format to Anthropic tool format."""
        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
        return anthropic_tools

    def _build_messages(self, messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert messages to Anthropic format, extracting system message."""
        system_message: str | None = None
        anthropic_messages: list[dict[str, Any]] = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            if msg.role == "system":
                system_message = msg.content
            elif msg.role == "user":
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool_call" and msg.tool_call:
                # Anthropic includes tool_use in assistant message content
                anthropic_messages.append({
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": msg.tool_call.call_id,
                        "name": msg.tool_call.name,
                        "input": msg.tool_call.args,
                    }],
                })
            elif msg.role == "tool_result" and msg.call_id:
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.call_id,
                        "content": msg.content,
                    }],
                })

            i += 1

        return system_message, anthropic_messages

    def generate(self, messages: list[Message]) -> Generator[str | ToolCall, None, None]:
        """
        Generate a streaming response from Anthropic.

        Args:
            messages: The conversation history.

        Yields:
            String chunks for text responses, or ToolCall objects at the end.
        """
        if not self.quiet:
            print("Waiting on LLM...", flush=True)

        system_message, anthropic_messages = self._build_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 8192,
            "stream": True,
        }
        if system_message:
            kwargs["system"] = system_message
        if self.tools:
            kwargs["tools"] = self.tools

        # Check if model supports extended thinking
        if "claude-3-7" in self.model or "claude-sonnet-4" in self.model or "claude-opus-4" in self.model:
            budget_tokens_map = {"low": 2000, "medium": 5000, "high": 10000}
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens_map[self.reasoning_level]}
            kwargs["temperature"] = 1  # Required for extended thinking

        tool_calls: list[ToolCall] = []
        current_tool: dict[str, Any] | None = None
        thinking_content: list[str] = []
        in_thinking = False

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "thinking":
                        in_thinking = True
                        if not self.quiet:
                            print("\n[Thinking]", flush=True)
                    elif block.type == "tool_use":
                        current_tool = {
                            "id": block.id,
                            "name": block.name,
                            "input": "",
                        }
                        if not self.quiet:
                            yield f"\n[Tool Call: {block.name}]\n"

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        thinking_content.append(delta.thinking)
                        if not self.quiet:
                            print(delta.thinking, end="", flush=True)
                    elif delta.type == "text_delta":
                        yield delta.text
                    elif delta.type == "input_json_delta":
                        if current_tool is not None:
                            current_tool["input"] += delta.partial_json
                        if not self.quiet:
                            yield delta.partial_json

                elif event.type == "content_block_stop":
                    if in_thinking:
                        if not self.quiet:
                            print("\n[/Thinking]\n", flush=True)
                        in_thinking = False
                    elif current_tool is not None:
                        if not self.quiet:
                            yield "\n[/Tool Call]\n"
                        tool_calls.append(ToolCall(
                            name=current_tool["name"],
                            args=json.loads(current_tool["input"]) if current_tool["input"] else {},
                            call_id=current_tool["id"],
                        ))
                        current_tool = None

        # Log thinking to Braintrust trace if available
        if thinking_content and BRAINTRUST_API_KEY and BRAINTRUST_PROJECT:
            try:
                from braintrust import current_span

                span = current_span()
                if span:
                    span.log(metadata={"thinking": "".join(thinking_content)})
            except Exception:
                pass  # Braintrust span not available

        for tc in tool_calls:
            yield tc
