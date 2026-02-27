#!/usr/bin/env python3
"""
Verify that all files referenced in project JSONs exist and follow naming conventions.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# Naming convention patterns
NAMING_PATTERNS = {
    'confluence': r'^[a-z0-9-]+\.json$',
    'fireflies': r'^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.json$',
    'github': r'^pr-\d+\.json$',
    'gmail': r'^thread-\d{8}-[a-f0-9]{8}\.json$',
    'google_drive': r'^[a-z0-9-]+\.json$',
    'hubspot': r'^[a-z_]+\.json$',
    'jira': r'^(SUP|INT)-\d+\.json$',
    'linear': r'^[A-Z]+-\d+(-[a-z0-9-]+)?\.json$',
    'slack': r'^\d+\.json$',
}

# Additional rules
FORBIDDEN_PATTERNS = {
    'fireflies': [r'^ff-', r'^ff_'],  # NO ff- or ff_ prefix
    'github': [r'^pr_', r'pr-\d+-.*'],  # dash not underscore, no description
    'gmail': [r'thread-\d{8}-[a-f0-9]{9,}', r'thread-\d{8}-.*-'],  # exactly 8 char hash, no description
    'slack': [r'^thread-'],  # NO thread- prefix
}


def extract_source_type(path: str) -> str:
    """Extract the source type from a path like 'sources/confluence/...'"""
    parts = path.split('/')
    if len(parts) >= 2 and parts[0] == 'sources':
        return parts[1]
    return 'unknown'


def check_naming_convention(filename: str, source_type: str) -> Tuple[bool, str]:
    """Check if filename follows naming convention for its source type."""

    # Check pattern match
    if source_type in NAMING_PATTERNS:
        pattern = NAMING_PATTERNS[source_type]
        if not re.match(pattern, filename):
            return False, f"Does not match pattern {pattern}"

    # Check forbidden patterns
    if source_type in FORBIDDEN_PATTERNS:
        for forbidden in FORBIDDEN_PATTERNS[source_type]:
            if re.search(forbidden, filename):
                return False, f"Matches forbidden pattern {forbidden}"

    return True, ""


def verify_project_files(project_path: str, base_dir: Path) -> Dict:
    """Verify all files in a project JSON."""

    with open(project_path, 'r') as f:
        project = json.load(f)

    results = {
        'project_path': project_path,
        'total_files': len(project.get('files', [])),
        'missing_files': [],
        'naming_violations': [],
        'status': 'PASS'
    }

    for file_entry in project.get('files', []):
        file_path = file_entry['path']

        # Build full path
        full_path = base_dir / 'data_clean' / file_path

        # Check if file exists
        if not full_path.exists():
            results['missing_files'].append({
                'path': file_path,
                'description': file_entry.get('description', '')
            })
            results['status'] = 'FAIL'

        # Check naming convention
        filename = Path(file_path).name
        source_type = extract_source_type(file_path)

        is_valid, reason = check_naming_convention(filename, source_type)
        if not is_valid:
            results['naming_violations'].append({
                'path': file_path,
                'source_type': source_type,
                'filename': filename,
                'reason': reason
            })
            results['status'] = 'FAIL'

    return results


def print_results(results: Dict):
    """Print verification results in a readable format."""

    project_name = Path(results['project_path']).stem
    print(f"\n{'='*80}")
    print(f"PROJECT: {project_name}")
    print(f"{'='*80}")
    print(f"Total files checked: {results['total_files']}")

    # Missing files
    if results['missing_files']:
        print(f"\nMISSING FILES ({len(results['missing_files'])}):")
        for item in results['missing_files']:
            print(f"  - {item['path']}")
            if item['description']:
                print(f"    Description: {item['description'][:100]}...")
    else:
        print("\nMISSING FILES: None")

    # Naming violations
    if results['naming_violations']:
        print(f"\nNAMING VIOLATIONS ({len(results['naming_violations'])}):")
        for item in results['naming_violations']:
            print(f"  - {item['path']}")
            print(f"    Source: {item['source_type']}")
            print(f"    Filename: {item['filename']}")
            print(f"    Reason: {item['reason']}")
    else:
        print("\nNAMING VIOLATIONS: None")

    # Status
    print(f"\nSTATUS: {results['status']}")


def main():
    base_dir = Path('/Users/yuhongsun/Projects/IndustryRAG-Dataset')

    projects = [
        'data_clean/projects/rbac_v2_design_permission_inventory.json',
        'data_clean/projects/burst_capacity_option_implementation.json',
        'data_clean/projects/dedicated_staged_rollouts_for_reserved_pools.json',
        'data_clean/projects/route_level_a_b_testing_framework.json',
        'data_clean/projects/model_metadata_schema_changelog_generator.json',
        'data_clean/projects/perf_regression_canary_in_prod.json',
    ]

    all_results = []
    summary = defaultdict(int)

    for project_path in projects:
        full_project_path = base_dir / project_path
        if not full_project_path.exists():
            print(f"ERROR: Project file not found: {project_path}")
            continue

        results = verify_project_files(str(full_project_path), base_dir)
        all_results.append(results)
        print_results(results)

        # Update summary
        summary['total_projects'] += 1
        summary['total_files'] += results['total_files']
        summary['total_missing'] += len(results['missing_files'])
        summary['total_violations'] += len(results['naming_violations'])
        if results['status'] == 'PASS':
            summary['passed_projects'] += 1
        else:
            summary['failed_projects'] += 1

    # Print overall summary
    print(f"\n{'='*80}")
    print("OVERALL SUMMARY")
    print(f"{'='*80}")
    print(f"Total projects checked: {summary['total_projects']}")
    print(f"Total files checked: {summary['total_files']}")
    print(f"Total missing files: {summary['total_missing']}")
    print(f"Total naming violations: {summary['total_violations']}")
    print(f"Projects PASSED: {summary['passed_projects']}")
    print(f"Projects FAILED: {summary['failed_projects']}")
    print(f"\nFinal status: {'PASS' if summary['failed_projects'] == 0 else 'FAIL'}")


if __name__ == '__main__':
    main()
