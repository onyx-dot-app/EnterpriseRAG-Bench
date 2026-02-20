"""Write the source directory tree to a file."""

import subprocess

from src.paths import SOURCES_DIR, SOURCE_TREE_PATH


def main() -> None:
    print("Step 6: Write Source Directory Tree")
    print("=" * 40)
    print("This script saves the current source directory structure to a file.")
    print("This provides a snapshot of the directory layout for reference.")
    print()

    # Run tree command on sources directory (directories only)
    result = subprocess.run(
        ["tree", "-d", SOURCES_DIR],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error running tree command: {result.stderr}")
        return

    tree_output = result.stdout

    # Write to file
    with open(SOURCE_TREE_PATH, "w") as f:
        f.write(tree_output)

    print(tree_output)
    print()
    print(f"✓ Saved source directory tree to {SOURCE_TREE_PATH}")


if __name__ == "__main__":
    main()
