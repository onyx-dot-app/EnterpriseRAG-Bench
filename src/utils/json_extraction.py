"""JSON extraction utilities for LLM responses."""

import json
import re


def extract_json_from_response(response: str) -> str:
    """
    Extract JSON from LLM response by finding the outermost JSON structure.

    Tries multiple strategies:
    1. Find first '{' or '[' and match with last '}' or ']'
    2. Fallback: Look for JSON in markdown code blocks
    3. Fallback: Use regex to find JSON object/array

    Args:
        response: The LLM response text.

    Returns:
        The extracted JSON string.
    """
    response = response.strip()

    # Strategy 1: Find outermost JSON structure
    first_brace = response.find("{")
    first_bracket = response.find("[")

    if first_brace != -1 or first_bracket != -1:
        if first_brace == -1:
            start = first_bracket
            close_char = "]"
        elif first_bracket == -1:
            start = first_brace
            close_char = "}"
        elif first_brace < first_bracket:
            start = first_brace
            close_char = "}"
        else:
            start = first_bracket
            close_char = "]"

        last_close = response.rfind(close_char)
        if last_close != -1 and last_close >= start:
            candidate = response[start : last_close + 1]
            # Validate it's parseable JSON before returning
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass  # Fall through to backup strategies

    # Strategy 2 (fallback): Try to find JSON in a markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if json_match:
        candidate = json_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Strategy 3 (fallback): Regex for JSON object or array
    json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
    if json_match:
        return json_match.group(1)

    return response
