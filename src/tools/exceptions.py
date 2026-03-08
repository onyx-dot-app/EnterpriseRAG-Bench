"""Exception classes for tool execution control flow."""


class ToolTerminationSignal(Exception):
    """Raised by a tool to signal that the conversation should terminate successfully.

    This is not an error — it indicates the tool completed its work and no further
    LLM rounds are needed. The result message is appended to the conversation
    as a normal tool result before returning.
    """

    def __init__(self, result: str):
        self.result = result
        super().__init__(result)
