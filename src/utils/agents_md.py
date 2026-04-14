"""Utility for building agents.md file content blocks."""

import os

from src.paths import AGENTS_MD_FILE, SOURCES_DIR


def get_agents_md_for_source(source_type: str) -> str:
    """
    Get all agents.md files and their contents for a specific source type.

    Args:
        source_type: Name of the source type (e.g., "confluence").

    Returns:
        Formatted string containing all agents.md paths and contents.
    """
    source_path = os.path.join(SOURCES_DIR, source_type)
    if not os.path.exists(source_path):
        return f"(No agents.md files found for {source_type})"

    agents_sections = []

    for root, _dirs, files in os.walk(source_path):
        if AGENTS_MD_FILE in files:
            agents_path = os.path.join(root, AGENTS_MD_FILE)
            rel_path = os.path.relpath(agents_path, SOURCES_DIR)

            try:
                with open(agents_path) as f:
                    content = f.read().strip()
                if content:
                    formatted = f"""agents.md file path: {rel_path}
agents.md file contents:
```
{content}
```"""
                    agents_sections.append(formatted)
            except Exception:
                pass

    if not agents_sections:
        return f"(No agents.md files found for {source_type})"

    return "\n\n".join(agents_sections)


def get_agents_md_for_path(file_path: str) -> str:
    """
    Get agents.md files relevant to a file path.

    Looks for agents.md files in the file's source type directory.

    Args:
        file_path: Path relative to SOURCES_DIR (e.g., "confluence/docs/file.json").

    Returns:
        Formatted string containing relevant agents.md paths and contents.
    """
    # Get the source type (top-level directory)
    parts = file_path.split(os.sep)
    if not parts:
        return "(No agents.md files found)"

    source_type = parts[0]
    return get_agents_md_for_source(source_type)
