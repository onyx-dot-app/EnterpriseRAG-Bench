"""Script for generating near-duplicate files to add noise to the dataset."""

import argparse
import json
import os
import random
import subprocess

from src.llm import Message, get_llm
from src.paths import (
    QUESTION_CACHE_DIR,
    SOURCES_DIR,
    SOURCE_TREE_PATH,
)
from src.prompts.new_duplicate_file import (
    FILE_MOVE_PROMPT,
    FILE_PATH_INVALID_RESPONSE,
    FILE_RENAME_PROMPT,
    NEW_DUPLICATE_FILE_PROMPT,
    NEW_DUPLICATE_FILE_USER_PROMPT,
)
from src.utils import (
    count_json_files,
    extract_json_from_response,
    get_agents_md_for_path,
    get_dataset_doc_uuid,
    JsonRecoveryError,
    load_file,
    process_written_document,
    select_random_file_hierarchical,
    try_recover_json,
    validate_no_nested_dicts,
    write_json_file,
)


# =============================================================================
# Source Tree
# =============================================================================


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


# =============================================================================
# Path Validation
# =============================================================================


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


# =============================================================================
# Generation Functions
# =============================================================================


def generate_new_file_path(
    file_path: str,
    file_contents: str,
    source_tree: str,
    max_attempts: int = 5,
) -> str | None:
    """
    Generate a new file path for a near-duplicate file.

    Two-step process:
    1. Generate a new directory path (may have any filename)
    2. Rename the file to follow naming conventions for the target source type

    Args:
        file_path: Original file path relative to SOURCES_DIR.
        file_contents: Original file contents as string.
        source_tree: Directory tree structure.
        max_attempts: Maximum attempts to generate a valid path.

    Returns:
        New file path relative to SOURCES_DIR, or None if all attempts fail.
    """
    print("\n" + "=" * 40)
    print("Phase 1a: Generate New File Path")
    print("=" * 40)

    prompt = FILE_MOVE_PROMPT.format(
        file_path=file_path,
        file_contents=file_contents,
        source_directory_structure=source_tree,
    )

    llm = get_llm(tools=None, quiet=False)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"\nAttempt {attempt + 1}/{max_attempts}...")

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                response += chunk
        print()

        response = response.strip()

        # Clean up the response (remove any markdown, quotes, etc.)
        new_path = response.strip("`\"' \n")

        # Remove "sources/" prefix if present
        if new_path.startswith("sources/"):
            new_path = new_path[8:]

        # Ensure it ends with .json
        if not new_path.endswith(".json"):
            new_path += ".json"

        # Validate the parent directory exists
        if validate_file_path(new_path):
            print(f"\nValid directory path: {os.path.dirname(new_path)}")

            # Add response to messages for context
            messages.append(Message(role="assistant", content=response))

            # Now rename the file using naming conventions
            final_path = _rename_file_for_source(
                new_path=new_path,
                file_path=file_path,
                messages=messages,
                llm=llm,
                max_attempts=max_attempts,
            )

            if final_path:
                return final_path

            # Rename failed, retry from the beginning
            print("\nRename failed, retrying path generation...")
        else:
            print(f"\nInvalid path (parent dir doesn't exist): {new_path}")

        # Invalid path, retry
        if attempt < max_attempts - 1:
            messages.append(Message(role="assistant", content=response))
            messages.append(Message(role="user", content=FILE_PATH_INVALID_RESPONSE))

    print("\nFailed to generate valid path after all attempts")
    return None


def _rename_file_for_source(
    new_path: str,
    file_path: str,
    messages: list[Message],
    llm: object,
    max_attempts: int = 3,
) -> str | None:
    """
    Rename a file to follow the naming conventions of the target source type.

    Args:
        new_path: Initial new path (directory is valid but filename may not follow conventions).
        file_path: Original file path (to avoid returning the same path).
        messages: Conversation history to continue from.
        llm: LLM instance to use.
        max_attempts: Maximum attempts to generate a valid filename.

    Returns:
        Final valid path or None if all attempts fail.
    """
    print("\n" + "=" * 40)
    print("Phase 1b: Rename File for Source Type")
    print("=" * 40)

    # Get the target directory
    target_dir = os.path.dirname(new_path)

    # Get agents.md for the target source type
    agents_md_contents = get_agents_md_for_path(new_path)

    # Build the rename prompt
    rename_prompt = FILE_RENAME_PROMPT.format(agents_md_contents=agents_md_contents)
    messages.append(Message(role="user", content=rename_prompt))

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"\nRename attempt {attempt + 1}/{max_attempts}...")

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                response += chunk
        print()

        response = response.strip()

        # Clean up the response (remove any markdown, quotes, etc.)
        new_filename = response.strip("`\"' \n")

        # Ensure it ends with .json
        if not new_filename.endswith(".json"):
            new_filename += ".json"

        # Build the full path
        final_path = os.path.join(target_dir, new_filename) if target_dir else new_filename

        # Validate the final path
        if final_path != file_path:
            full_final_path = os.path.join(SOURCES_DIR, final_path)
            if not os.path.exists(full_final_path):
                print(f"\nValid final path: {final_path}")
                return final_path
            else:
                print(f"\nFile already exists: {final_path}")
        else:
            print("\nSame as original path")

        # Invalid, retry
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
    print("\n" + "=" * 40)
    print("Phase 2: Generate New File Contents")
    print("=" * 40)

    # Get agents.md for the new file path's source type
    agents_md_contents = get_agents_md_for_path(new_file_path)

    system_prompt = NEW_DUPLICATE_FILE_PROMPT.format(
        file_path=file_path,
        file_contents=file_contents,
        agents_md_contents=agents_md_contents,
        new_file_path=new_file_path,
    )

    llm = get_llm(tools=None, quiet=False)
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=NEW_DUPLICATE_FILE_USER_PROMPT),
    ]

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"\nAttempt {attempt + 1}/{max_attempts}...")

        response = ""
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                response += chunk
        print()

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
                    response = try_recover_json(response, quiet=False)
                    data = json.loads(response)
                except JsonRecoveryError:
                    if attempt < max_attempts - 1:
                        messages.append(Message(role="assistant", content=response))
                        messages.append(
                            Message(
                                role="user",
                                content="That was not valid JSON. Please output only valid JSON with no nested objects.",
                            )
                        )
                    continue

        # Validate no nested dicts
        validation_error = validate_no_nested_dicts(data)
        if validation_error:
            print(f"\nValidation error: {validation_error}")
            if attempt < max_attempts - 1:
                messages.append(Message(role="assistant", content=response))
                messages.append(
                    Message(
                        role="user",
                        content=f"Error: {validation_error}. All values must be strings, primitives, or lists of strings. Please fix and try again.",
                    )
                )
            continue

        print("\nValid JSON generated")
        return response

    print("\nFailed to generate valid contents after all attempts")
    return None


# =============================================================================
# Main Generation Loop
# =============================================================================


def generate_near_duplicate(
    file_path: str,
    source_tree: str,
) -> tuple[bool, str, str | None, str | None]:
    """
    Generate a near-duplicate file for a given source file.

    Args:
        file_path: Path to the original file relative to SOURCES_DIR.
        source_tree: Directory tree structure.

    Returns:
        (success, message, old_file_path, new_file_path) tuple.
        On failure, old_file_path and new_file_path are None.
    """
    full_path = os.path.join(SOURCES_DIR, file_path)

    # Load the original file
    try:
        file_contents = load_file(full_path)
    except Exception as e:
        return (False, f"Error loading file: {e}", None, None)

    # Generate new file path
    new_file_path = generate_new_file_path(
        file_path=file_path,
        file_contents=file_contents,
        source_tree=source_tree,
    )

    if not new_file_path:
        return (False, "Failed to generate valid new file path", None, None)

    # Print the selected path between the two prompts
    print("\n" + "=" * 40)
    print("Selected Paths")
    print("=" * 40)
    print(f"Original: {file_path}")
    print(f"New:      {new_file_path}")

    # Generate new file contents
    new_contents = generate_new_file_contents(
        file_path=file_path,
        file_contents=file_contents,
        new_file_path=new_file_path,
    )

    if not new_contents:
        return (False, "Failed to generate valid new file contents", None, None)

    # Write the new file with noise marker
    full_new_path = os.path.join(SOURCES_DIR, new_file_path)
    try:
        # Add dataset_noise_document field before writing
        data = json.loads(new_contents)
        data["dataset_noise_document"] = True
        with open(full_new_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nWrote file: {new_file_path}")
    except Exception as e:
        return (False, f"Error writing file: {e}", None, None)

    # Add field labels and UUID
    print("\nProcessing document (labels + UUID)...")
    success, error = process_written_document(full_new_path, quiet=False)
    if not success:
        return (False, f"Error processing document: {error}", None, None)
    print("Document processed")

    return (True, f"Created {new_file_path}", file_path, new_file_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate near-duplicate files to add noise to the dataset."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of near-duplicate files to generate (default: 20)",
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

    # Count JSON files
    total_files = count_json_files()

    if total_files == 0:
        print("No JSON files found in sources directory.")
        return

    print(f"Found {total_files} JSON files in sources.")
    print(f"Will generate {args.count} near-duplicate(s).")
    print()

    # Get source tree
    source_tree = get_source_tree()

    # Ensure question cache directory exists
    os.makedirs(QUESTION_CACHE_DIR, exist_ok=True)

    # Find the next duplication number
    existing_duplications = [
        f for f in os.listdir(QUESTION_CACHE_DIR)
        if f.startswith("duplication_") and f.endswith(".json")
    ]
    if existing_duplications:
        max_num = max(
            int(f.replace("duplication_", "").replace(".json", ""))
            for f in existing_duplications
        )
        duplication_counter = max_num + 1
    else:
        duplication_counter = 1

    success_count = 0
    fail_count = 0
    errors: list[str] = []
    used_source_files: set[str] = set()

    for i in range(args.count):
        print("\n" + "#" * 60)
        print(f"# Near-Duplicate {i + 1} of {args.count}")
        print("#" * 60)

        # Select a random file using hierarchical random walk
        file_path = select_random_file_hierarchical()

        if not file_path:
            print("Failed to select a file")
            fail_count += 1
            errors.append("Failed to select a file")
            continue

        # Try to avoid selecting the same source file twice
        attempts = 0
        while file_path in used_source_files and attempts < 10:
            file_path = select_random_file_hierarchical()
            attempts += 1
            if file_path is None:
                break

        if file_path is None:
            print("Failed to select a file")
            fail_count += 1
            errors.append("Failed to select a file")
            continue

        print(f"\nSelected source file: {file_path}")

        success, message, old_path, new_path = generate_near_duplicate(file_path, source_tree)

        if success and old_path and new_path:
            success_count += 1
            used_source_files.add(file_path)

            # Get UUIDs from both files
            old_full_path = os.path.join(SOURCES_DIR, old_path)
            new_full_path = os.path.join(SOURCES_DIR, new_path)

            old_uuid = get_dataset_doc_uuid(old_full_path)
            new_uuid = get_dataset_doc_uuid(new_full_path)

            # Write duplication cache file
            cache_filename = f"duplication_{duplication_counter:04d}.json"
            cache_path = os.path.join(QUESTION_CACHE_DIR, cache_filename)
            cache_data = {
                "document_old": old_uuid,
                "document_new": new_uuid,
            }
            write_json_file(cache_path, cache_data)
            print(f"\nWrote cache: {cache_filename}")

            duplication_counter += 1
            print(f"\nSUCCESS: {message}")
        else:
            fail_count += 1
            errors.append(f"{file_path}: {message}")
            print(f"\nFAILED: {message}")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
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
