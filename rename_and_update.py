#!/usr/bin/env python3
"""
Script to rename files based on source type conventions and update project JSON files.
"""
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path("/Users/yuhongsun/Projects/IndustryRAG-Dataset/data_clean")

# Project files to process
PROJECT_FILES = [
    "projects/enterprise_security_enablement_kit_update.json",
    "projects/hosted_data_residency_enforcement.json",
    "projects/multi_gpu_tp_stability_fixes.json",
    "projects/retention_controls_compliance_reporting_pack.json",
    "projects/hosted_circuit_breakers_load_shedding.json",
    "projects/optimization_suggestions_console_ux_beta.json",
]

def determine_new_name(source_type: str, current_name: str, file_path: Path) -> str:
    """Determine the correct new name based on source type conventions."""

    # GitHub: pr-1234.json (pr- prefix + digits)
    if source_type == "github":
        # Extract PR number from various formats
        match = re.search(r'pr[_-](\d+)', current_name, re.IGNORECASE)
        if match:
            pr_num = match.group(1)
            return f"pr-{pr_num}.json"

    # Fireflies: 2025-01-28-meeting-title.json (date + meeting title with dashes)
    elif source_type == "fireflies":
        # Remove ff_ prefix and convert underscores to dashes
        if current_name.startswith("ff_"):
            new_name = current_name[3:]  # Remove ff_ prefix
            new_name = new_name.replace("_", "-")  # Convert underscores to dashes
            return new_name

    # Slack: Unix timestamp only like 1234567890.json (no underscores, just digits)
    elif source_type == "slack":
        # Extract just the numeric timestamp
        match = re.match(r'(\d+)', current_name)
        if match:
            timestamp = match.group(1)
            return f"{timestamp}.json"

    # Gmail: thread-yearmonthday-sha.json format
    elif source_type == "gmail":
        # Convert underscores to dashes if needed
        if "thread" in current_name:
            new_name = current_name.replace("_", "-")
            # Ensure format is thread-...
            if not new_name.startswith("thread-"):
                new_name = new_name.replace("thread_", "thread-", 1)
            return new_name

    # Linear: First 3 letters of team like ABC-12345.json (1-5 digits)
    elif source_type == "linear":
        # Already mostly correct format
        return current_name

    # Jira: SUP-12345.json or INT-12345.json
    elif source_type == "jira":
        # Already mostly correct format
        return current_name

    # Confluence, Google Drive, HubSpot: Short descriptive with dashes
    elif source_type in ["confluence", "google_drive", "hubspot"]:
        # Convert underscores to dashes
        new_name = current_name.replace("_", "-")
        return new_name

    # Default: return original name
    return current_name

def get_renames_for_project(project_path: Path) -> List[Tuple[str, str, str]]:
    """
    Get list of files that need renaming for a project.
    Returns: List of (old_path, new_path, old_project_path)
    """
    renames = []

    with open(project_path, 'r') as f:
        project_data = json.load(f)

    for file_entry in project_data.get("files", []):
        old_rel_path = file_entry["path"]

        # Parse the path to determine source type
        parts = old_rel_path.split("/")
        if len(parts) < 2 or parts[0] != "sources":
            continue

        source_type = parts[1]
        current_filename = parts[-1]

        # Determine new name
        new_filename = determine_new_name(source_type, current_filename, Path(old_rel_path))

        # If name changed, add to rename list
        if new_filename != current_filename:
            new_rel_path = "/".join(parts[:-1] + [new_filename])
            old_full_path = BASE_DIR / old_rel_path
            new_full_path = BASE_DIR / new_rel_path

            # Only add if old file exists
            if old_full_path.exists():
                renames.append((str(old_full_path), str(new_full_path), old_rel_path))

    return renames

def main():
    """Main execution function."""
    all_renames = {}  # Map old_rel_path -> new_rel_path
    project_updates = {}  # Map project_file -> list of (old_path, new_path)

    print("=" * 80)
    print("STEP 1: ANALYZING FILES FOR RENAMING")
    print("=" * 80)

    # Collect all renames needed
    for project_file in PROJECT_FILES:
        project_path = BASE_DIR / project_file
        print(f"\nProcessing: {project_file}")

        renames = get_renames_for_project(project_path)
        project_updates[project_file] = []

        for old_full, new_full, old_rel in renames:
            new_rel = "/".join(old_rel.split("/")[:-1] + [Path(new_full).name])
            all_renames[old_rel] = new_rel
            project_updates[project_file].append((old_rel, new_rel))
            print(f"  {old_rel}")
            print(f"    -> {new_rel}")

    print(f"\n\nTotal files to rename: {len(all_renames)}")

    if not all_renames:
        print("No files need renaming!")
        return

    # Perform file renames
    print("\n" + "=" * 80)
    print("STEP 2: RENAMING FILES")
    print("=" * 80)

    renamed_count = 0
    for old_rel, new_rel in sorted(all_renames.items()):
        old_full = BASE_DIR / old_rel
        new_full = BASE_DIR / new_rel

        if old_full.exists():
            print(f"Renaming: {old_rel}")
            print(f"      to: {new_rel}")
            shutil.move(str(old_full), str(new_full))
            renamed_count += 1
        else:
            print(f"SKIP (not found): {old_rel}")

    print(f"\nRenamed {renamed_count} files successfully.")

    # Update project JSON files
    print("\n" + "=" * 80)
    print("STEP 3: UPDATING PROJECT JSON FILES")
    print("=" * 80)

    for project_file, updates in project_updates.items():
        if not updates:
            continue

        project_path = BASE_DIR / project_file
        print(f"\nUpdating: {project_file}")

        with open(project_path, 'r') as f:
            project_data = json.load(f)

        # Create mapping of old to new paths
        path_map = {old: new for old, new in updates}

        # Update file entries
        for file_entry in project_data.get("files", []):
            old_path = file_entry["path"]
            if old_path in path_map:
                new_path = path_map[old_path]
                file_entry["path"] = new_path
                print(f"  Updated: {old_path}")
                print(f"        to: {new_path}")

        # Write back to file
        with open(project_path, 'w') as f:
            json.dump(project_data, f, indent=2, ensure_ascii=False)

        print(f"  Saved {len(updates)} path updates to {project_file}")

    print("\n" + "=" * 80)
    print("COMPLETE!")
    print("=" * 80)
    print(f"Files renamed: {renamed_count}")
    print(f"Project files updated: {len([p for p, u in project_updates.items() if u])}")

if __name__ == "__main__":
    main()
