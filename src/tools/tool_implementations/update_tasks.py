"""Tool for updating a task checklist during project enrichment."""

from src.tools import UPDATE_TASKS_TOOL
from src.tools.interface import ToolInterface


class UpdateTasksTool(ToolInterface):
    """Tool for updating a task checklist (replaces entire list each time)."""

    def __init__(self, initial_tasks: str = ""):
        """
        Initialize the UpdateTasksTool.

        Args:
            initial_tasks: The initial tasks content.
        """
        self._tasks = initial_tasks

    @property
    def name(self) -> str:
        return UPDATE_TASKS_TOOL

    @property
    def tasks(self) -> str:
        """Returns the current tasks."""
        return self._tasks

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": (
                "Update the task checklist. It should be a short list of tasks with the markdown checkbox format. "
                "Note: The entire checklist is replaced each time you call this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "string",
                        "description": (
                            "The complete task checklist. Use markdown checkbox format, "
                            "e.g. '- [ ] Task 1\\n- [x] Task 2 (done)'."
                        ),
                    },
                },
                "required": ["tasks"],
            },
        }

    def execute(self, tasks: str) -> str:  # type: ignore[override]
        """
        Update the tasks.

        Args:
            tasks: The new tasks content (replaces existing).

        Returns:
            Confirmation message.
        """
        self._tasks = tasks
        return "Tasks updated successfully."
