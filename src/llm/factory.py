import os

from src.llm.interface import LLMInterface, ReasoningLevel


LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME")
CHEAP_LLM_MODEL_NAME = os.environ.get("CHEAP_LLM_MODEL_NAME")


def get_llm(
    tools: list[dict] | None = None,
    quiet: bool = False,
    reasoning_level: ReasoningLevel = "medium",
    model: str | None = None,
) -> LLMInterface:
    """
    Get the default LLM based on LLM_PROVIDER environment variable.

    Args:
        tools: List of tool schemas in OpenAI format.
        quiet: If True, suppress status print statements (useful for parallel calls).
        reasoning_level: Level of reasoning effort ("low", "medium", "high").
        model: Override the model name (default: LLM_MODEL_NAME env var).

    Returns:
        An LLM instance configured based on environment variables.

    Raises:
        ValueError: If LLM_PROVIDER is not supported.
    """
    provider = LLM_PROVIDER.lower()

    if provider == "openai":
        from src.llm.openai_llm import OpenAILLM

        return OpenAILLM(
            model=model, tools=tools, quiet=quiet, reasoning_level=reasoning_level
        )
    elif provider == "anthropic":
        from src.llm.anthropic_llm import AnthropicLLM

        return AnthropicLLM(
            model=model, tools=tools, quiet=quiet, reasoning_level=reasoning_level
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            "Supported providers: openai, anthropic"
        )


def get_cheap_llm(
    tools: list[dict] | None = None,
    quiet: bool = False,
    reasoning_level: ReasoningLevel = "medium",
    model: str | None = None,
) -> LLMInterface:
    """
    Get a cheap/fast LLM based on LLM_PROVIDER environment variable.

    Uses CHEAP_LLM_MODEL_NAME instead of LLM_MODEL_NAME.

    Args:
        tools: List of tool schemas in OpenAI format.
        quiet: If True, suppress status print statements (useful for parallel calls).
        reasoning_level: Level of reasoning effort ("low", "medium", "high").
        model: Override the model name (default: CHEAP_LLM_MODEL_NAME env var).

    Returns:
        An LLM instance configured with the cheap model.

    Raises:
        ValueError: If LLM_PROVIDER is not supported.
    """
    provider = LLM_PROVIDER.lower()

    if provider == "openai":
        from src.llm.openai_llm import (
            CHEAP_LLM_MODEL_NAME as OPENAI_CHEAP_MODEL,
            OpenAILLM,
        )

        return OpenAILLM(
            model=model or OPENAI_CHEAP_MODEL,
            tools=tools,
            quiet=quiet,
            reasoning_level=reasoning_level,
        )
    elif provider == "anthropic":
        from src.llm.anthropic_llm import (
            CHEAP_LLM_MODEL_NAME as ANTHROPIC_CHEAP_MODEL,
            AnthropicLLM,
        )

        return AnthropicLLM(
            model=model or ANTHROPIC_CHEAP_MODEL,
            tools=tools,
            quiet=quiet,
            reasoning_level=reasoning_level,
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            "Supported providers: openai, anthropic"
        )
