"""Tool for reading the employee directory."""

from src.paths import EMPLOYEE_DIRECTORY_PATH
from src.tools import READ_EMPLOYEE_DIRECTORY_TOOL
from src.tools.interface import ToolInterface


class ReadEmployeeDirectoryTool(ToolInterface):
    """Tool for reading the employee directory."""

    @property
    def name(self) -> str:
        return READ_EMPLOYEE_DIRECTORY_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": "Read the employee directory YAML file to get information about employees, departments, titles, and reporting structure.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

    def execute(self) -> str:
        """
        Read the employee directory.

        Returns:
            The employee directory contents or error message.
        """
        try:
            with open(EMPLOYEE_DIRECTORY_PATH) as f:
                content = f.read()
            if not content.strip():
                return f"Error: Employee directory at {EMPLOYEE_DIRECTORY_PATH} is empty"
            return content
        except FileNotFoundError:
            return f"Error: Employee directory not found at {EMPLOYEE_DIRECTORY_PATH}"
        except Exception as e:
            return f"Error reading employee directory: {e}"
