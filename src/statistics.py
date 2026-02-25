"""Utility for tracking aggregate statistics across steps."""

import os
import re
from datetime import datetime
from typing import Any

from src.paths import AGGREGATE_STATISTICS_PATH


def _format_value(key: str, value: Any) -> str:
    """Format a single key-value pair for display."""
    # Convert snake_case to Title Case
    display_key = key.replace("_", " ").title()

    if isinstance(value, list):
        # Format list as indented items
        lines = [f"{display_key}:"]
        for item in value:
            lines.append(f"  - {item}")
        return "\n".join(lines)
    elif isinstance(value, dict):
        # Format dict as indented key-value pairs
        lines = [f"{display_key}:"]
        for k, v in sorted(value.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
            lines.append(f"  - {k}: {v}")
        return "\n".join(lines)
    else:
        return f"{display_key}: {value}"


def _format_step_section(step_name: str, stats: dict[str, Any]) -> str:
    """Format a step's statistics as a text section."""
    lines = [f"## {step_name}"]
    for key, value in stats.items():
        lines.append(_format_value(key, value))
    return "\n".join(lines)


def _parse_existing_stats(content: str) -> dict[str, str]:
    """
    Parse existing statistics file into sections by step name.

    Returns dict mapping step names to their full section content.
    """
    sections: dict[str, str] = {}

    # Split by step headers (## Step X: ...)
    pattern = r"(## Step \d+: [^\n]+)"
    parts = re.split(pattern, content)

    # parts will be: [header_content, step1_name, step1_content, step2_name, step2_content, ...]
    i = 1
    while i < len(parts) - 1:
        step_name = parts[i].replace("## ", "").strip()
        step_content = parts[i + 1].strip()
        sections[step_name] = f"## {step_name}\n{step_content}"
        i += 2

    return sections


def update_statistics(step_name: str, stats: dict[str, Any]) -> None:
    """
    Update the aggregate statistics file with new stats from a step.

    Reads existing file, updates/replaces the section for this step,
    and writes back. Preserves other step sections.

    Args:
        step_name: Name of the step (e.g., "Step 3: Employee Directory")
        stats: Dictionary of statistics to record
    """
    # Read existing content if file exists
    existing_sections: dict[str, str] = {}
    if os.path.exists(AGGREGATE_STATISTICS_PATH):
        with open(AGGREGATE_STATISTICS_PATH) as f:
            content = f.read()
        existing_sections = _parse_existing_stats(content)

    # Update/add this step's section
    existing_sections[step_name] = _format_step_section(step_name, stats)

    # Build output with header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"""================================================================================
AGGREGATE STATISTICS
Last updated: {timestamp}
================================================================================
"""

    # Sort sections by step number
    def step_sort_key(name: str) -> int:
        match = re.search(r"Step (\d+)", name)
        return int(match.group(1)) if match else 999

    sorted_sections = sorted(existing_sections.items(), key=lambda x: step_sort_key(x[0]))

    # Combine all sections
    output = header + "\n" + "\n\n".join(section for _, section in sorted_sections) + "\n"

    # Write output
    with open(AGGREGATE_STATISTICS_PATH, "w") as f:
        f.write(output)
