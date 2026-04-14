"""Date utilities."""

from datetime import datetime


def get_current_date_formatted() -> str:
    """Get the current date formatted as 'Month DD, YYYY'.

    Returns:
        Formatted date string (e.g., "January 15, 2024").
    """
    return datetime.now().strftime("%B %d, %Y")
