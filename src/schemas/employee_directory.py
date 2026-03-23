"""Schema for employee directory validation."""

import yaml
from pydantic import BaseModel, EmailStr, field_validator


class Employee(BaseModel):
    """Schema for an employee entry."""

    name: str
    title: str
    email: EmailStr
    start_date: str
    manager: str | None = None
    bio: str

    @field_validator("start_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date is in YYYY-MM-DD format."""
        import re

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("start_date must be in YYYY-MM-DD format")
        return v


class EmployeeDirectory(BaseModel):
    """Schema for the employee directory."""

    departments: dict[str, list[Employee]]


EXPECTED_FORMAT = """
departments:
  <DepartmentName>:
    - name: "Full Name"
      title: "Job Title"
      email: "email@company.com"
      start_date: "YYYY-MM-DD"
      manager: "Manager Name"  # optional, omit for top-level executives
      bio: "Brief bio or background"
""".strip()


def validate_employee_directory(content: str) -> str | None:
    """
    Validate employee directory YAML content.

    Args:
        content: The YAML content to validate.

    Returns:
        None if valid, error message string if invalid.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return f"Invalid YAML syntax: {e}"

    try:
        EmployeeDirectory.model_validate(data)
    except Exception as e:
        return f"Schema validation failed: {e}"

    return None
