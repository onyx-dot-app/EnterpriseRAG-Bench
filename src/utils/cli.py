"""CLI utilities for interactive prompts."""


def confirm_yes_no(
    prompt: str,
    default: bool | None = None,
    retry_on_invalid: bool = False,
) -> bool:
    """Prompt user for a yes/no confirmation.

    Args:
        prompt: The question to ask the user (without the [y/n] suffix).
        default: Default value if user presses enter without input.
            True = default yes [Y/n], False = default no [y/N], None = no default [y/n].
        retry_on_invalid: If True, keep prompting until valid input is received.
            If False, treat invalid input as the default (or False if no default).

    Returns:
        True if user confirms, False otherwise.
    """
    if default is True:
        hint = "[Y/n]"
    elif default is False:
        hint = "[y/N]"
    else:
        hint = "[y/n]"

    full_prompt = f"{prompt} {hint}: "

    while True:
        response = input(full_prompt).strip().lower()

        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        elif response == "" and default is not None:
            return default
        elif retry_on_invalid:
            print("Please enter 'y' or 'n'.")
        else:
            return default if default is not None else False


def confirm_regenerate(data_description: str) -> bool:
    """Prompt user to confirm regeneration of existing data.

    Args:
        data_description: Description of the data to regenerate (e.g., "Company overview").

    Returns:
        True if user confirms regeneration, False otherwise.
    """
    return confirm_yes_no(
        f"{data_description} already exists. Regenerate?", default=False
    )
