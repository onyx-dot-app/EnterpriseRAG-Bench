"""CLI utilities for interactive prompts."""


def confirm_regenerate(data_description: str) -> bool:
    """Prompt user to confirm regeneration of existing data.

    Args:
        data_description: Description of the data to regenerate (e.g., "Company overview").

    Returns:
        True if user confirms regeneration, False otherwise.
    """
    response = input(f"{data_description} already exists. Regenerate? [y/N]: ").strip().lower()
    return response in ("y", "yes")
