"""Validate employee directory and print org chart."""

import yaml

from src.paths import EMPLOYEE_DIRECTORY_PATH
from src.schemas.employee_directory import EmployeeDirectory


def load_employee_directory() -> EmployeeDirectory:
    """Load and parse the employee directory."""
    with open(EMPLOYEE_DIRECTORY_PATH) as f:
        data = yaml.safe_load(f)
    return EmployeeDirectory.model_validate(data)


def check_duplicate_emails(directory: EmployeeDirectory) -> list[str]:
    """Check for duplicate emails. Returns list of errors."""
    emails: dict[str, str] = {}  # email -> name
    errors: list[str] = []

    for dept, employees in directory.departments.items():
        for emp in employees:
            if emp.email in emails:
                errors.append(
                    f"Duplicate email '{emp.email}': "
                    f"used by both '{emails[emp.email]}' and '{emp.name}'"
                )
            else:
                emails[emp.email] = emp.name

    return errors


def build_name_to_employee_map(
    directory: EmployeeDirectory,
) -> dict[str, tuple[str, str]]:
    """Build a map of name -> (department, title) for all employees."""
    name_map: dict[str, tuple[str, str]] = {}
    for dept, employees in directory.departments.items():
        for emp in employees:
            name_map[emp.name] = (dept, emp.title)
    return name_map


def check_manager_validity(directory: EmployeeDirectory) -> list[str]:
    """Check that all managers exist in the directory. Returns list of errors."""
    name_map = build_name_to_employee_map(directory)
    errors: list[str] = []

    for dept, employees in directory.departments.items():
        for emp in employees:
            if emp.manager and emp.manager not in name_map:
                errors.append(
                    f"'{emp.name}' has manager '{emp.manager}' who doesn't exist"
                )

    return errors


def check_cycles(directory: EmployeeDirectory) -> list[str]:
    """Check for cycles in the reporting structure. Returns list of errors."""
    # Build manager graph: employee -> manager
    manager_of: dict[str, str | None] = {}

    for dept, employees in directory.departments.items():
        for emp in employees:
            manager_of[emp.name] = emp.manager

    errors: list[str] = []

    for name in manager_of:
        visited: set[str] = set()
        current: str | None = name

        while current is not None:
            if current in visited:
                cycle_start = current
                # Reconstruct cycle for error message
                cycle: list[str] = [cycle_start]
                current = manager_of[cycle_start]
                while current != cycle_start:
                    cycle.append(current)  # type: ignore
                    current = manager_of[current]  # type: ignore
                cycle.append(cycle_start)
                errors.append(f"Cycle detected: {' -> '.join(cycle)}")
                break

            visited.add(current)
            current = manager_of.get(current)

    # Deduplicate cycle errors (same cycle can be detected from multiple nodes)
    return list(set(errors))


def build_org_tree(
    directory: EmployeeDirectory,
) -> dict[str, list[str]]:
    """Build a tree of reports: manager -> list of direct reports."""
    reports: dict[str, list[str]] = {}

    for dept, employees in directory.departments.items():
        for emp in employees:
            manager = emp.manager or "__ROOT__"
            if manager not in reports:
                reports[manager] = []
            reports[manager].append(emp.name)

    return reports


def get_employee_info(directory: EmployeeDirectory, name: str) -> str:
    """Get formatted employee info string."""
    for dept, employees in directory.departments.items():
        for emp in employees:
            if emp.name == name:
                return f"{emp.name} ({emp.title}, {dept})"
    return name


def print_tree(
    directory: EmployeeDirectory,
    reports: dict[str, list[str]],
    node: str,
    prefix: str = "",
    is_last: bool = True,
) -> None:
    """Recursively print the org tree."""
    connector = "└── " if is_last else "├── "
    info = get_employee_info(directory, node)
    print(f"{prefix}{connector}{info}")

    if node in reports:
        children = sorted(reports[node])
        for i, child in enumerate(children):
            is_child_last = i == len(children) - 1
            child_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(directory, reports, child, child_prefix, is_child_last)


def print_org_chart(directory: EmployeeDirectory) -> None:
    """Print the full org chart."""
    reports = build_org_tree(directory)
    roots = reports.get("__ROOT__", [])

    if not roots:
        print("No top-level employees found (everyone has a manager)")
        return

    print("\n" + "=" * 60)
    print("ORG CHART")
    print("=" * 60 + "\n")

    for i, root in enumerate(sorted(roots)):
        info = get_employee_info(directory, root)
        print(f"🏢 {info}")
        if root in reports:
            children = sorted(reports[root])
            for j, child in enumerate(children):
                is_last = j == len(children) - 1
                print_tree(directory, reports, child, "", is_last)
        if i < len(roots) - 1:
            print()


def main() -> None:
    print("Employee Directory Validator")
    print("=" * 40)

    # Load directory
    try:
        directory = load_employee_directory()
        print(f"✓ Loaded {EMPLOYEE_DIRECTORY_PATH}")
    except Exception as e:
        print(f"✗ Failed to load directory: {e}")
        return

    # Count employees
    total = sum(len(emps) for emps in directory.departments.values())
    print(f"✓ Found {total} employees across {len(directory.departments)} departments")

    # Run validations
    all_errors: list[str] = []

    email_errors = check_duplicate_emails(directory)
    if email_errors:
        all_errors.extend(email_errors)
        print(f"✗ Duplicate emails: {len(email_errors)} errors")
    else:
        print("✓ No duplicate emails")

    manager_errors = check_manager_validity(directory)
    if manager_errors:
        all_errors.extend(manager_errors)
        print(f"✗ Invalid managers: {len(manager_errors)} errors")
    else:
        print("✓ All managers exist")

    cycle_errors = check_cycles(directory)
    if cycle_errors:
        all_errors.extend(cycle_errors)
        print(f"✗ Cycles detected: {len(cycle_errors)} errors")
    else:
        print("✓ No cycles in reporting structure")

    # Print errors if any
    if all_errors:
        print("\n" + "-" * 40)
        print("ERRORS:")
        for error in all_errors:
            print(f"  • {error}")
        print("-" * 40)
        return

    # Print org chart
    print_org_chart(directory)
    print("\n✓ Validation complete - no errors found")


if __name__ == "__main__":
    main()
