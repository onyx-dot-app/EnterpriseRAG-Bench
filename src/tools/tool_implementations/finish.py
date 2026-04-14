from src.tools import FINISH_TOOL
from src.tools.interface import ToolInterface


class FinishTool(ToolInterface):
    """Tool for signaling that the current step is complete."""

    def __init__(self) -> None:
        self._finished = False
        self._finish_info: str | None = None

    @property
    def name(self) -> str:
        return FINISH_TOOL

    @property
    def finished(self) -> bool:
        """Returns True if the finish tool has been called."""
        return self._finished

    @property
    def finish_info(self) -> str | None:
        """Returns the finish_info passed when finish was called, if any."""
        return self._finish_info

    def reset(self) -> None:
        """Reset the finished state."""
        self._finished = False
        self._finish_info = None

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": "Signal that the current step is complete and ready to proceed to the next phase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "finish_info": {
                        "type": "string",
                        "description": "Optional information to pass when finishing (e.g., a question or summary).",
                    },
                },
                "required": [],
            },
        }

    def execute(self, finish_info: str | None = None) -> str:  # type: ignore[override]
        """Mark the step as finished.

        Args:
            finish_info: Optional information to store when finishing.
        """
        self._finished = True
        self._finish_info = finish_info
        return "Step marked as complete."
