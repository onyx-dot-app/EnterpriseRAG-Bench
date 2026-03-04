"""Script for generating near-duplicate files to add noise to the dataset."""

import argparse
import json
import os
import random
import subprocess

from tqdm import tqdm

from src.llm import Message, get_cheap_llm
from src.paths import (
    SOURCES_DIR,
    SOURCE_TREE_PATH,
)
from src.prompts.json_recovery import JSON_RECOVERY_PROMPT
from src.prompts.new_duplicate_file import (
    FILE_MOVE_PROMPT,
    FILE_PATH_INVALID_RESPONSE,
    NEW_DUPLICATE_FILE_PROMPT,
    NEW_DUPLICATE_FILE_USER_PROMPT,
)
from src.utils import (
    extract_json_from_response,
    get_agents_md_for_path,
    load_file,
    process_written_document,
    validate_no_nested_dicts,
)


class JsonRecoveryError(Exception):
    """Raised when JSON recovery fails after all attempts."""
    pass


def get_all_json_files() -> list[str]:
    """
    Get all JSON files from the sources directory.

    Returns:
        List of file paths relative to SOURCES_DIR.
    """
    json_files = []

    for root, _dirs, files in os.walk(SOURCES_DIR):
        for filename in files:
            if filename.endswith(".json"):
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, SOURCES_DIR)
                json_files.append(rel_path)

    return json_files


def get_source_tree() -> str:
    """
    Get the full directory tree for all sources.

    Returns:
        Tree output string for the sources directory.
    """
    if os.path.exists(SOURCE_TREE_PATH):
        return load_file(SOURCE_TREE_PATH)

    result = subprocess.run(
        ["tree", "-d"],
        cwd=SOURCES_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return f"(Error running tree: {result.stderr})"

    return result.stdout


def validate_file_path(file_path: str) -> bool:
    """
    Validate that a file path is valid (parent directory exists).

    Args:
        file_path: Path relative to SOURCES_DIR.

    Returns:
        True if the parent directory exists, False otherwise.
    """
    full_path = os.path.join(SOURCES_DIR, file_path)
    parent_dir = os.path.dirname(full_path)
    return os.path.exists(parent_dir) and os.path.isdir(parent_dir)


def try_recover_json(broken_json: str, max_attempts: int = 3) -> str:
    """
    Attempt to recover broken JSON using cheap LLM with conversation history.

    Args:
        broken_json: The broken JSON string.
        max_attempts: Maximum number of recovery attempts.

    Returns:
        Recovered JSON string.

    Raises:
        JsonRecoveryError: If recovery fails after all attempts.
    """
    prompt = JSON_RECOVERY_PROMPT.format(broken_json_string=broken_json)
    llm = get_cheap_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        response = response.strip()

        # Try to parse the response
        try:
            json.loads(response)
            return response
        except json.JSONDecodeError as e:
            # Try to extract JSON from the response
            try:
                extracted = extract_json_from_response(response)
                json.loads(extracted)
                return extracted
            except Exception:
                pass

            # If not last attempt, add to conversation and retry
            if attempt < max_attempts - 1:
                messages.append(Message(role="assistant", content=response))
                messages.append(Message(
                    role="user",
                    content=f"That JSON is still invalid: {e}. Please fix it and output only valid JSON.",
                ))

    raise JsonRecoveryError(f"JSON recovery failed after {max_attempts} attempts")


def generate_new_file_path(
    file_path: str,
    file_contents: str,
    source_tree: str,
    max_attempts: int = 5,
) -> str | None:
    """
    Generate a new file path for a near-duplicate file.

    Args:
        file_path: Original file path relative to SOURCES_DIR.
        file_contents: Original file contents as string.
        source_tree: Directory tree structure.
        max_attempts: Maximum attempts to generate a valid path.

    Returns:
        New file path relative to SOURCES_DIR, or None if all attempts fail.
    """
    prompt = FILE_MOVE_PROMPT.format(
        file_path=file_path,
        file_contents=file_contents,
        source_directory_structure=source_tree,
    )

    llm = get_cheap_llm(tools=None, quiet=True)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        response = response.strip()

        # Clean up the response (remove any markdown, quotes, etc.)
        new_path = response.strip("`\"' \n")

        # Remove "sources/" prefix if present
        if new_path.startswith("sources/"):
            new_path = new_path[8:]

        # Ensure it ends with .json
        if not new_path.endswith(".json"):
            new_path += ".json"

        # Validate the path
        if validate_file_path(new_path):
            # Also check it's not the same as the original
            if new_path != file_path:
                # Check the file doesn't already exist
                full_new_path = os.path.join(SOURCES_DIR, new_path)
                if not os.path.exists(full_new_path):
                    return new_path

        # Invalid path, retry
        if attempt < max_attempts - 1:
            messages.append(Message(role="assistant", content=response))
            messages.append(Message(role="user", content=FILE_PATH_INVALID_RESPONSE))

    return None


def generate_new_file_contents(
    file_path: str,
    file_contents: str,
    new_file_path: str,
    max_attempts: int = 3,
) -> str | None:
    """
    Generate new file contents for a near-duplicate file.

    Args:
        file_path: Original file path relative to SOURCES_DIR.
        file_contents: Original file contents as string.
        new_file_path: New file path relative to SOURCES_DIR.
        max_attempts: Maximum attempts to generate valid contents.

    Returns:
        New file contents as JSON string, or None if all attempts fail.
    """
    # Get agents.md for the new file path's source type
    agents_md_contents = get_agents_md_for_path(new_file_path)

    system_prompt = NEW_DUPLICATE_FILE_PROMPT.format(
        file_path=file_path,
        file_contents=file_contents,
        agents_md_contents=agents_md_contents,
        new_file_path=new_file_path,
    )

    llm = get_cheap_llm(tools=None, quiet=True)
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=NEW_DUPLICATE_FILE_USER_PROMPT),
    ]

    for attempt in range(max_attempts):
        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                response += chunk

        response = response.strip()

        # Try to parse JSON
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON
            try:
                response = extract_json_from_response(response)
                data = json.loads(response)
            except Exception:
                # Try JSON recovery
                try:
                    response = try_recover_json(response)
                    data = json.loads(response)
                except JsonRecoveryError:
                    if attempt < max_attempts - 1:
                        messages.append(Message(role="assistant", content=response))
                        messages.append(Message(
                            role="user",
                            content="That was not valid JSON. Please output only valid JSON with no nested objects.",
                        ))
                    continue

        # Validate no nested dicts
        validation_error = validate_no_nested_dicts(data)
        if validation_error:
            if attempt < max_attempts - 1:
                messages.append(Message(role="assistant", content=response))
                messages.append(Message(
                    role="user",
                    content=f"Error: {validation_error}. All values must be strings, primitives, or lists of strings. Please fix and try again.",
                ))
            continue

        return response

    return None


def generate_near_duplicate(
    file_path: str,
    source_tree: str,
) -> tuple[bool, str]:
    """
    Generate a near-duplicate file for a given source file.

    Args:
        file_path: Path to the original file relative to SOURCES_DIR.
        source_tree: Directory tree structure.

    Returns:
        (success, message) tuple.
    """
    full_path = os.path.join(SOURCES_DIR, file_path)

    # Load the original file
    try:
        file_contents = load_file(full_path)
    except Exception as e:
        return (False, f"Error loading file: {e}")

    # Generate new file path
    new_file_path = generate_new_file_path(
        file_path=file_path,
        file_contents=file_contents,
        source_tree=source_tree,
    )

    if not new_file_path:
        return (False, "Failed to generate valid new file path")

    # Generate new file contents
    new_contents = generate_new_file_contents(
        file_path=file_path,
        file_contents=file_contents,
        new_file_path=new_file_path,
    )

    if not new_contents:
        return (False, "Failed to generate valid new file contents")

    # Write the new file
    full_new_path = os.path.join(SOURCES_DIR, new_file_path)
    try:
        with open(full_new_path, "w") as f:
            f.write(new_contents)
    except Exception as e:
        return (False, f"Error writing file: {e}")

    # Add field labels and UUID
    success, error = process_written_document(full_new_path)
    if not success:
        return (False, f"Error processing document: {error}")

    return (True, f"Created {new_file_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate near-duplicate files to add noise to the dataset."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of near-duplicate files to generate (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    print("Step 1: Generate Near-Duplicate Files")
    print("=" * 40)
    print("This script generates near-duplicate files to add noise to the dataset.")
    print("Each near-duplicate is a newer version of an existing document in a")
    print("different location with some facts updated.")
    print()

    if args.seed is not None:
        random.seed(args.seed)
        print(f"Random seed: {args.seed}")

    # Get all JSON files
    json_files = get_all_json_files()

    if not json_files:
        print("No JSON files found in sources directory.")
        return

    print(f"Found {len(json_files)} JSON files in sources.")
    print(f"Will generate {args.count} near-duplicate(s).")
    print()

    # Get source tree
    source_tree = get_source_tree()

    # Select random files to create duplicates from
    if args.count > len(json_files):
        print(f"Warning: Requested {args.count} duplicates but only {len(json_files)} files available.")
        selected_files = json_files
    else:
        selected_files = random.sample(json_files, args.count)

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for file_path in tqdm(selected_files, desc="Generating near-duplicates"):
        success, message = generate_near_duplicate(file_path, source_tree)

        if success:
            success_count += 1
            tqdm.write(f"[OK] {file_path} -> {message}")
        else:
            fail_count += 1
            errors.append(f"{file_path}: {message}")
            tqdm.write(f"[FAIL] {file_path}: {message}")

    print()
    print("=" * 40)
    print("Summary")
    print("=" * 40)
    print(f"Successfully created: {success_count}")
    print(f"Failed: {fail_count}")

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")


if __name__ == "__main__":
    main()
