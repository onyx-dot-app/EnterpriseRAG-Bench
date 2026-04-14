"""Validation utilities for JSON documents."""


def is_simple_value(val: object) -> bool:
    """Check if a value is a simple string, primitive, or list of strings/primitives."""
    if isinstance(val, (str, int, float, bool, type(None))):
        return True
    if isinstance(val, list):
        return all(
            isinstance(item, (str, int, float, bool, type(None))) for item in val
        )
    return False


def validate_no_nested_dicts(data: dict) -> str | None:
    """
    Validate that a JSON dict has no nested dicts.

    All values must be strings, primitives, or lists of strings/primitives.

    Args:
        data: The parsed JSON dict.

    Returns:
        None if valid, error message if nested dicts found.
    """
    if not isinstance(data, dict):
        return "Top-level must be a dict"

    nested_keys = []
    for key, value in data.items():
        if not is_simple_value(value):
            nested_keys.append(key)

    if nested_keys:
        return f"Nested dicts found in keys: {nested_keys}"

    return None
