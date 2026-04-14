"""Utility for recovering broken JSON using LLM."""

import json

from src.llm import Message, get_cheap_llm
from src.prompts.json_recovery import JSON_RECOVERY_PROMPT
from src.utils.json_extraction import extract_json_from_response


class JsonRecoveryError(Exception):
    """Raised when JSON recovery fails after all attempts."""

    pass


def try_recover_json(
    broken_json: str,
    max_attempts: int = 3,
    quiet: bool = True,
) -> str:
    """
    Attempt to recover broken JSON using cheap LLM with conversation history.

    Args:
        broken_json: The broken JSON string.
        max_attempts: Maximum number of recovery attempts.
        quiet: If True, suppress LLM output. If False, stream output to console.

    Returns:
        Recovered JSON string.

    Raises:
        JsonRecoveryError: If recovery fails after all attempts.
    """
    if not quiet:
        print("\n" + "-" * 40)
        print("Attempting JSON recovery...")
        print("-" * 40)

    prompt = JSON_RECOVERY_PROMPT.format(broken_json_string=broken_json)
    llm = get_cheap_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        if not quiet and attempt > 0:
            print(f"\nRecovery attempt {attempt + 1}/{max_attempts}...")

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                if not quiet:
                    print(chunk, end="", flush=True)
                response += chunk

        if not quiet:
            print()

        response = response.strip()

        # Try to parse the response
        try:
            json.loads(response)
            if not quiet:
                print("JSON recovery successful")
            return response
        except json.JSONDecodeError as e:
            # Try to extract JSON from the response
            try:
                extracted = extract_json_from_response(response)
                json.loads(extracted)
                if not quiet:
                    print("JSON recovery successful (extracted)")
                return extracted
            except Exception:
                pass

            # If not last attempt, add to conversation and retry
            if attempt < max_attempts - 1:
                messages.append(Message(role="assistant", content=response))
                messages.append(
                    Message(
                        role="user",
                        content=f"That JSON is still invalid: {e}. Please fix it and output only valid JSON.",
                    )
                )

    raise JsonRecoveryError(f"JSON recovery failed after {max_attempts} attempts")
