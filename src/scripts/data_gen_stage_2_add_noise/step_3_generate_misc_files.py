"""Script for generating miscellaneous directories and files to add noise to the dataset.

Runs in two phases: (1) interactive LLM-guided creation of misc-type directories
(e.g. slack/memes, google_drive/.../misc-assets), and (2) parallel generation of
informal, off-topic documents within those directories. These peripheral documents
create retrieval challenges for questions targeting loosely organized content.

Usage:
    python -m src.scripts.data_gen_stage_2_add_noise.step_3_generate_misc_files [OPTIONS]

Args:
    --count        Total number of miscellaneous files to generate (default: 20)
    --parallelism  Number of files to generate in parallel (default: 5)
"""

import argparse
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from src.llm import Message, get_cheap_llm, get_llm
from src.llm.auto_conversation import run_auto_conversation
from src.llm.conversation import Conversation
from src.paths import (
    AGENTS_MD_FILE,
    COMPANY_OVERVIEW_PATH,
    SOURCES_DIR,
    SOURCE_TREE_PATH,
)
from src.prompts.misc_files import (
    DIRECTORY_ERROR_MESSAGE,
    MISC_FILES_PROMPT,
    MISC_FILES_SYSTEM_PROMPT,
)
from src.tools import MKDIR_TOOL
from src.tools.interface import ToolInterface
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import FinishTool, WriteTool
from src.utils import (
    delete_file,
    get_dataset_doc_uuid,
    get_directory_tree,
    load_file,
    load_json_file,
    misc_files_cache,
    sources_resolver,
    write_json_file,
)
from src.paths import GENERATION_CACHE_DIR
from src.utils.statistics import update_statistics

STEP_OVERVIEW = """\
Adds informal, off-topic documents in misc-type directories (e.g. slack/memes,
google_drive/.../misc-assets). These peripheral documents sit outside the main
scaffolding and create retrieval challenges due to their unpredictable locations.

Phases:
  1. Interactively create miscellaneous directories
  2. Generate miscellaneous files in those directories
"""


# =============================================================================
# Cache
# =============================================================================


def load_cache() -> dict:
    """
    Load the misc files cache.

    Returns:
        Cache dict with "directories" and "files" keys, or empty structure.
    """
    if os.path.exists(misc_files_cache.path):
        try:
            return load_json_file(misc_files_cache.path)
        except Exception:
            pass
    return {"directories": [], "files": []}


def save_cache(cache: dict) -> None:
    """Save the misc files cache."""
    os.makedirs(GENERATION_CACHE_DIR, exist_ok=True)
    write_json_file(misc_files_cache.path, cache)


# =============================================================================
# Source Tree
# =============================================================================


def get_source_tree() -> str:
    """
    Get the full directory tree for all sources, starting from sources/.

    Returns:
        Tree output string for the sources directory.
    """
    if os.path.exists(SOURCE_TREE_PATH):
        return load_file(SOURCE_TREE_PATH)
    return get_directory_tree(SOURCES_DIR)


# =============================================================================
# Single-Level Mkdir Tool
# =============================================================================


class SingleLevelMkdirTool(ToolInterface):
    """Mkdir tool that only allows creating directories where the parent already exists."""

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._created_dirs: list[str] = []

    @property
    def name(self) -> str:
        return MKDIR_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": f"Create a directory under {self._base_dir}. "
            "The parent directory must already exist (only 1 level can be created at a time).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to create (relative to base directory)",
                    },
                },
                "required": ["path"],
            },
        }

    @property
    def created_dirs(self) -> list[str]:
        """Return list of directories created (relative to base_dir)."""
        return self._created_dirs.copy()

    def execute(self, path: str) -> str:  # type: ignore[override]
        """
        Create a directory, ensuring the parent directory already exists.

        Args:
            path: The directory path to create (relative to base directory).

        Returns:
            Success or error message (includes DIRECTORY_ERROR_MESSAGE on failure).
        """
        path = path.lstrip("/")
        if ".." in path:
            return f"Error: Path cannot contain '..'\n\n{DIRECTORY_ERROR_MESSAGE}"

        # Strip base dir prefix if LLM includes it
        base_name = os.path.basename(self._base_dir)
        if path.startswith(f"{base_name}/"):
            path = path[len(base_name) + 1 :]
        elif path == base_name:
            return f"Error: Cannot create the base directory itself.\n\n{DIRECTORY_ERROR_MESSAGE}"

        full_path = os.path.join(self._base_dir, path)
        parent_dir = os.path.dirname(full_path)

        # Validate parent directory exists
        if not os.path.isdir(parent_dir):
            return (
                f"Error: Parent directory does not exist: {os.path.relpath(parent_dir, self._base_dir)}. "
                f"You can only create 1 level of directory at a time.\n\n{DIRECTORY_ERROR_MESSAGE}"
            )

        # Check if directory already exists
        if os.path.isdir(full_path):
            return (
                f"Error: Directory already exists: {path}\n\n{DIRECTORY_ERROR_MESSAGE}"
            )

        try:
            os.mkdir(full_path)
            self._created_dirs.append(path)
            return f"Successfully created directory: {path}"
        except Exception as e:
            return f"Error creating directory {path}: {e}\n\n{DIRECTORY_ERROR_MESSAGE}"


# =============================================================================
# Phase 1: Create Miscellaneous Directories
# =============================================================================


def create_misc_directories() -> list[str]:
    """
    Interactively create miscellaneous directories using LLM and user input.

    Returns:
        List of created directory paths (relative to SOURCES_DIR).
    """
    print()
    print("=" * 40)
    print("Phase 1: Create Miscellaneous Directories")
    print("=" * 40)
    print()
    print("The LLM will propose miscellaneous directories to create.")
    print("Confirm each directory before it is created.")
    print("Type 'quit' to stop creating directories and move to Phase 2.")
    print()

    source_tree = get_source_tree()

    system_prompt = MISC_FILES_SYSTEM_PROMPT.format(
        source_directory_structure=source_tree,
    )

    # Set up tools
    mkdir_tool = SingleLevelMkdirTool(base_dir=SOURCES_DIR)
    finish_tool = FinishTool()

    tool_runner = ToolRunner()
    tool_runner.register(mkdir_tool)
    tool_runner.register(finish_tool)

    llm = get_llm(tools=[mkdir_tool.schema, finish_tool.schema], quiet=False)

    conv = Conversation(llm=llm, tool_runner=tool_runner)
    conv.add_system_message(system_prompt)

    # Initial prompt to start proposing directories
    conv.add_user_message(
        "Please propose miscellaneous directories to add to the dataset."
    )
    conv.generate_response()
    print()

    # Interactive loop - exits when finish tool is called or user quits
    conv.run_interactive_loop(finish_tool=finish_tool)

    created_dirs = mkdir_tool.created_dirs

    print()
    print(f"Created {len(created_dirs)} miscellaneous directory/directories:")
    for d in created_dirs:
        print(f"  - {d}")

    return created_dirs


# =============================================================================
# Phase 2: Generate Miscellaneous Files
# =============================================================================


def get_existing_misc_files(misc_directories: list[str]) -> list[str]:
    """
    Get list of existing JSON files in miscellaneous directories.

    Args:
        misc_directories: List of misc directory paths relative to SOURCES_DIR.

    Returns:
        List of file paths relative to SOURCES_DIR.
    """
    files = []
    for dir_path in misc_directories:
        full_dir = os.path.join(SOURCES_DIR, dir_path)
        if not os.path.isdir(full_dir):
            continue
        for filename in sorted(os.listdir(full_dir)):
            if filename.endswith(".json"):
                files.append(os.path.join(dir_path, filename))
    return files


def get_agents_md_for_misc_dirs(misc_directories: list[str]) -> str:
    """
    Get agents.md files that exist on the ancestor paths of the misc directories.

    For each misc directory, walks up from that directory to the SOURCES_DIR root,
    collecting any agents.md files found along the way.

    Args:
        misc_directories: List of misc directory paths relative to SOURCES_DIR.

    Returns:
        Formatted string with agents.md content for relevant paths.
    """
    # Collect unique agents.md paths (keyed by rel_path to deduplicate)
    agents_files: dict[str, str] = {}

    for dir_path in misc_directories:
        abs_dir = os.path.join(SOURCES_DIR, dir_path)
        current = abs_dir

        # Walk up from the misc directory to SOURCES_DIR
        while True:
            agents_path = os.path.join(current, AGENTS_MD_FILE)
            if os.path.isfile(agents_path):
                rel_path = os.path.relpath(agents_path, SOURCES_DIR)
                if rel_path not in agents_files:
                    try:
                        with open(agents_path) as f:
                            content = f.read().strip()
                        if content:
                            agents_files[rel_path] = content
                    except Exception:
                        pass

            # Stop once we've checked SOURCES_DIR itself
            if os.path.normpath(current) == os.path.normpath(SOURCES_DIR):
                break
            current = os.path.dirname(current)

    if not agents_files:
        return "(No agents.md files found)"

    sections = []
    for rel_path in sorted(agents_files):
        formatted = f"""agents.md file path: {rel_path}
agents.md file contents:
```
{agents_files[rel_path]}
```"""
        sections.append(formatted)

    return "\n\n".join(sections)


def generate_single_misc_file(
    company_overview: str,
    misc_directories: list[str],
    agents_md_contents: str,
    existing_files: list[str],
    quiet: bool = False,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """
    Generate a single miscellaneous file using auto conversation.

    Args:
        company_overview: Company overview content.
        misc_directories: List of misc directory paths relative to SOURCES_DIR.
        agents_md_contents: Formatted agents.md content for relevant source types.
        existing_files: List of existing file paths to encourage diversity.
        quiet: If True, suppress LLM output.
        max_retries: Maximum retries for file generation.

    Returns:
        (success, message) tuple where message is the dataset_doc_uuid on success.
    """
    misc_dirs_str = "\n".join(misc_directories)
    existing_str = "\n".join(existing_files) if existing_files else "(none)"

    prompt = MISC_FILES_PROMPT.format(
        company_overview=company_overview,
        agents_md_contents=agents_md_contents,
        misc_directories=misc_dirs_str,
        existing_misc_files=existing_str,
    )

    for retry in range(max_retries):
        write_tool = WriteTool(
            base_dir=SOURCES_DIR,
            is_document_json=True,
            mark_as_noise=True,
            auto_process=True,
            quiet=quiet,
            terminate_on_success=True,
        )

        llm = get_cheap_llm(
            tools=[write_tool.schema],
            quiet=quiet,
        )

        tool_runner = ToolRunner()
        tool_runner.register(write_tool)

        messages: list[Message] = [
            Message(role="user", content=prompt),
        ]

        try:
            run_auto_conversation(
                llm=llm,
                tool_runner=tool_runner,
                messages=messages,
                max_tool_cycles=10,
                max_iterations=30,
                quiet=quiet,
            )

            if not write_tool.written_paths:
                continue

            rel_path = write_tool.written_paths[0]
            abs_path = sources_resolver.to_absolute(rel_path)

            # Verify field labels exist — if labeling failed, delete and alert
            try:
                doc_data = load_json_file(abs_path)
            except Exception:
                delete_file(abs_path)
                return (False, f"Failed to read written file: {rel_path}")

            missing_fields = []
            if "title_field_name" not in doc_data:
                missing_fields.append("title_field_name")
            if "content_field_names" not in doc_data:
                missing_fields.append("content_field_names")

            if missing_fields:
                delete_file(abs_path)
                return (
                    False,
                    f"Field labeling failed for {rel_path} "
                    f"(missing: {', '.join(missing_fields)}). File deleted.",
                )

            doc_uuid = get_dataset_doc_uuid(abs_path)
            if not doc_uuid:
                delete_file(abs_path)
                return (
                    False,
                    f"File written but no UUID found: {rel_path}. File deleted.",
                )
            return (True, doc_uuid)

        except Exception as e:
            # Clean up any written files on error
            for rel_path in write_tool.written_paths:
                abs_path = os.path.join(SOURCES_DIR, rel_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            if retry == max_retries - 1:
                return (False, f"Error: {e}")

    return (False, "Max retries exceeded without creating valid file")


def generate_misc_files(
    company_overview: str,
    misc_directories: list[str],
    cache: dict,
    count: int = 20,
    parallelism: int = 5,
) -> list[str]:
    """
    Phase 2: Generate miscellaneous files in the created directories.

    Generates only the remaining files needed to reach `count`, based on
    what's already tracked in the cache.

    Args:
        company_overview: Company overview content.
        misc_directories: List of misc directory paths relative to SOURCES_DIR.
        cache: Cache dict to update with created files.
        count: Total desired number of misc files.
        parallelism: Number of files to generate in parallel.

    Returns:
        List of newly created file paths (relative to SOURCES_DIR).
    """
    print()
    print("=" * 40)
    print("Phase 2: Generate Miscellaneous Files")
    print("=" * 40)
    print()

    if not misc_directories:
        print("No miscellaneous directories to generate files for.")
        return []

    existing_count = len(cache.get("files", []))
    remaining = max(0, count - existing_count)

    if remaining == 0:
        print(f"Already have {existing_count}/{count} files. Nothing to generate.")
        return []

    print(
        f"Target: {count} files total ({existing_count} already exist, {remaining} remaining)"
    )
    print(f"Parallelism: {parallelism}")
    print()
    print("Miscellaneous directories:")
    for d in misc_directories:
        print(f"  - {d}")
    print()

    # Pre-load agents.md content for relevant source types
    agents_md_contents = get_agents_md_for_misc_dirs(misc_directories)

    # Get initial snapshot of existing files for diversity
    existing_files = get_existing_misc_files(misc_directories)

    # Track created files with a lock for thread safety
    created_files: list[str] = []
    created_lock = threading.Lock()

    total_success = 0
    total_fail = 0
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures: dict = {}

        for i in range(remaining):
            # Snapshot existing files, shuffled for variance
            with created_lock:
                snapshot = existing_files + created_files.copy()
            random.shuffle(snapshot)

            future = executor.submit(
                generate_single_misc_file,
                company_overview,
                misc_directories,
                agents_md_contents,
                snapshot,
                True,  # quiet=True for parallel
            )
            futures[future] = i

        with tqdm(total=remaining, desc="Generating misc files") as pbar:
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    success, message = future.result()
                    if success:
                        total_success += 1
                        with created_lock:
                            created_files.append(message)
                        # Update cache after each success
                        cache["files"].append(message)
                        save_cache(cache)
                    else:
                        total_fail += 1
                        errors.append(f"File {idx + 1}: {message}")
                except Exception as e:
                    total_fail += 1
                    errors.append(f"File {idx + 1}: {e}")

                pbar.update(1)

    # Summary
    print()
    print("=" * 40)
    print("Phase 2 Summary")
    print("=" * 40)
    print(f"Files created this run: {total_success}")
    print(f"Failures this run: {total_fail}")
    print(f"Total files in cache: {len(cache['files'])}")

    labeling_failures = [e for e in errors if "Field labeling failed" in e]
    if labeling_failures:
        print()
        print(
            f"WARNING: {len(labeling_failures)} file(s) deleted due to field labeling failure:"
        )
        for error in labeling_failures:
            print(f"  - {error}")

    other_errors = [e for e in errors if "Field labeling failed" not in e]
    if other_errors:
        print()
        print("Other errors:")
        for error in other_errors[:20]:
            print(f"  - {error}")
        if len(other_errors) > 20:
            print(f"  ... and {len(other_errors) - 20} more")

    return created_files


# =============================================================================
# Statistics
# =============================================================================


def _update_statistics(cache: dict) -> None:
    """Update aggregate statistics for this step."""
    directories = cache.get("directories", [])
    files = cache.get("files", [])

    # Count directories per source type
    per_source: dict[str, int] = {}
    for d in directories:
        source_type = d.split("/")[0] if "/" in d else "unknown"
        per_source[source_type] = per_source.get(source_type, 0) + 1

    update_statistics(
        "Stage 2: Add Noise",
        "Step 3: Miscellaneous Files",
        {
            "total_directories": len(directories),
            "total_files": len(files),
            "directories": directories,
            "directories_per_source": per_source,
        },
    )


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate miscellaneous directories and files to add noise to the dataset."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Total number of miscellaneous files to generate (default: 20)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=5,
        help="Number of files to generate in parallel (default: 5)",
    )
    args = parser.parse_args()

    print("Step 3: Generate Miscellaneous Files")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Verify sources directory exists
    if not os.path.isdir(SOURCES_DIR):
        print(f"Error: Sources directory not found: {SOURCES_DIR}")
        print("Please run earlier steps first.")
        return

    # Load company overview
    company_overview = load_file(COMPANY_OVERVIEW_PATH)

    # Check for existing cache
    cache = load_cache()
    cached_dirs = cache.get("directories", [])
    cached_files = cache.get("files", [])

    if cached_dirs:
        print(f"Found existing cache at {misc_files_cache.path}")
        print(f"  Directories: {len(cached_dirs)}")
        print(f"  Files: {len(cached_files)}")
        print()

        # Validate cached directories still exist
        valid_dirs = []
        for d in cached_dirs:
            full_path = os.path.join(SOURCES_DIR, d)
            if os.path.isdir(full_path):
                valid_dirs.append(d)
            else:
                print(f"  Warning: Cached directory no longer exists, removing: {d}")

        if valid_dirs != cached_dirs:
            cache["directories"] = valid_dirs
            save_cache(cache)

        misc_directories = valid_dirs

        print("Resuming with cached directories:")
        for d in misc_directories:
            print(f"  - {d}")
        print()
    else:
        # Phase 1: Create miscellaneous directories (interactive)
        misc_directories = create_misc_directories()

        if not misc_directories:
            print("\nNo miscellaneous directories created. Exiting.")
            return

        # Save directories to cache
        cache["directories"] = misc_directories
        save_cache(cache)

    # Phase 2: Generate miscellaneous files
    generate_misc_files(
        company_overview=company_overview,
        misc_directories=misc_directories,
        cache=cache,
        count=args.count,
        parallelism=args.parallelism,
    )

    # Final status
    total_files = len(cache.get("files", []))
    print()
    print("=" * 40)
    print(f"{total_files}/{args.count} miscellaneous files generated.")
    print(f"Cache saved to: {misc_files_cache.path}")
    print("=" * 40)

    # Update aggregate statistics
    _update_statistics(cache)

    print("\nThis step is complete, go on to step 4 to generate near-duplicate files.")


if __name__ == "__main__":
    main()
