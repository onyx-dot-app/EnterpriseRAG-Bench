from src.tools import FINISH_TOOL
from src.tools.interface import ToolInterface


class FinishTool(ToolInterface):
    """Tool for signaling that the current step is complete."""

    def __init__(self) -> None:
        self._finished = False

    @property
    def name(self) -> str:
        return FINISH_TOOL

    @property
    def finished(self) -> bool:
        """Returns True if the finish tool has been called."""
        return self._finished

    def reset(self) -> None:
        """Reset the finished state."""
        self._finished = False

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": "Signal that the current step is complete and ready to proceed to the next phase.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

    def execute(self) -> str:
        """Mark the step as finished."""
        self._finished = True
        return "Step marked as complete."
