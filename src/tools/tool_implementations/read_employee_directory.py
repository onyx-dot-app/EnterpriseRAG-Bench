"""Tool for reading and filtering the employee directory using an LLM."""

from src.llm.interface import LLMInterface, Message, ToolCall
from src.paths import EMPLOYEE_DIRECTORY_PATH
from src.tools import READ_EMPLOYEE_DIRECTORY_TOOL
from src.tools.interface import ToolInterface

SYSTEM_PROMPT = """You are a helpful assistant that filters employee directory data.

You will be given the full employee directory in YAML format and a query describing which employees to return.

Your task is to return ONLY the employees that match the query, in the same YAML format.

Rules:
- Return valid YAML with the same structure (departments -> list of employees)
- Only include departments that have matching employees
- If the query is "Everyone" or similar, return the entire directory unchanged
- If the query asks for a random subset, select a random sample across departments
- If no employees match, return an empty departments dict: "departments: {}"
- Do not add any explanation, just return the YAML
"""


class ReadEmployeeDirectoryTool(ToolInterface):
    """Tool for reading and filtering the employee directory."""

    def __init__(self, llm: LLMInterface):
        """
        Initialize the ReadEmployeeDirectoryTool.

        Args:
            llm: The LLM to use for filtering employees.
        """
        self._llm = llm

    @property
    def name(self) -> str:
        return READ_EMPLOYEE_DIRECTORY_TOOL

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": (
                "Read the employee directory and filter employees based on a query. "
                "Examples: 'Engineers working on auth', 'Random subset of 10 people', "
                "'Everyone', 'Managers in the Platform team', 'People who started in 2024', "
                "'A specific person by name'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "A natural language query describing which employees to return. "
                            "Use 'Everyone' to get the full directory."
                        ),
                    },
                },
                "required": ["query"],
            },
        }

    def execute(self, query: str) -> str:  # type: ignore[override]
        """
        Read and filter the employee directory based on the query.

        Args:
            query: Natural language query for filtering employees.

        Returns:
            YAML string containing matching employees.
        """
        try:
            with open(EMPLOYEE_DIRECTORY_PATH) as f:
                full_directory = f.read()
        except FileNotFoundError:
            return f"Error: Employee directory not found at {EMPLOYEE_DIRECTORY_PATH}"
        except Exception as e:
            return f"Error reading employee directory: {e}"

        # For "Everyone" queries, skip the LLM call
        query_lower = query.lower().strip()
        if query_lower in ("everyone", "all", "all employees", "the full directory"):
            return full_directory

        # Use the LLM to filter the directory
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(
                role="user",
                content=f"Here is the employee directory:\n\n```yaml\n{full_directory}\n```\n\nQuery: {query}\n\nReturn ONLY the matching employees in YAML format.",
            ),
        ]

        result_chunks: list[str] = []
        for chunk in self._llm.generate(messages):
            if isinstance(chunk, ToolCall):
                # Shouldn't happen, but handle gracefully
                break
            result_chunks.append(chunk)

        result = "".join(result_chunks)

        # Strip markdown code fences if present
        result = result.strip()
        if result.startswith("```yaml"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]

        return result.strip()
