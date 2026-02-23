import os

from src.llm.interface import LLMInterface


LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")


def get_llm(tools: list[dict] | None = None) -> LLMInterface:
    """
    Get the default LLM based on LLM_PROVIDER environment variable.

    Args:
        tools: List of tool schemas in OpenAI format.

    Returns:
        An LLM instance configured based on environment variables.

    Raises:
        ValueError: If LLM_PROVIDER is not supported.
    """
    provider = LLM_PROVIDER.lower()

    if provider == "openai":
        from src.llm.openai_llm import OpenAILLM
        return OpenAILLM(tools=tools)
    elif provider == "anthropic":
        from src.llm.anthropic_llm import AnthropicLLM
        return AnthropicLLM(tools=tools)
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            "Supported providers: openai, anthropic"
        )
