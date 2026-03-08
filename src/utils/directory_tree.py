"""Utility for generating directory tree representations."""

import os


def _build_tree_lines(
    dir_path: str,
    prefix: str = "",
    current_depth: int = 0,
) -> list[str]:
    """
    Recursively build tree lines for a directory.

    Args:
        dir_path: Path to the directory.
        prefix: Prefix string for indentation.
        current_depth: Current depth in the tree.

    Returns:
        List of formatted tree lines.
    """
    lines: list[str] = []

    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return [f"{prefix}[Permission Denied]"]

    # Filter to only directories
    dirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]

    for i, name in enumerate(dirs):
        is_last = i == len(dirs) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{name}/")

        # Recurse into subdirectory
        child_prefix = prefix + ("    " if is_last else "│   ")
        child_path = os.path.join(dir_path, name)
        lines.extend(_build_tree_lines(child_path, child_prefix, current_depth + 1))

    return lines


def get_directory_tree(base_dir: str) -> str:
    """
    Get a tree representation of a directory structure.

    This is a pure Python implementation that doesn't require the `tree` command.
    Shows only directories (not files), with paths relative to base_dir.

    Args:
        base_dir: The base directory to show tree for.

    Returns:
        Tree string showing directory structure.
    """
    if not os.path.isdir(base_dir):
        return f"{os.path.basename(base_dir)}/ (not found)"

    root_name = os.path.basename(base_dir.rstrip("/")) or base_dir
    lines = [f"{root_name}/"]
    lines.extend(_build_tree_lines(base_dir))

    if len(lines) == 1:
        return f"{root_name}/ (empty)"

    return "\n".join(lines)
