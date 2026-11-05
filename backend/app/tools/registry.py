"""Central Tool Registry managing native and MCP tools with least-privilege scoping."""

from typing import Any

from backend.app.core.errors import PermanentError
from backend.app.tools.base import BaseTool, ToolMetadata


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.metadata.name
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise PermanentError(
                f"Tool '{name}' not found in registry", details={"tool_name": name}
            )
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[ToolMetadata]:
        return [tool.metadata for tool in self._tools.values()]

    def get_scoped_tools(self, allowlist: list[str]) -> list[BaseTool]:
        """Return only tools permitted by an agent's allowlist (least-privilege)."""
        tools: list[BaseTool] = []
        for name in allowlist:
            if name in self._tools:
                tools.append(self._tools[name])
            else:
                raise PermanentError(
                    f"Allowlisted tool '{name}' is not registered", details={"tool_name": name}
                )
        return tools

    def export_schemas_for_llm(self, allowlist: list[str] | None = None) -> list[dict[str, Any]]:
        """Exports schemas in standard OpenAI/Anthropic tool calling specification."""
        tools_to_export = (
            [self.get(name) for name in allowlist]
            if allowlist is not None
            else list(self._tools.values())
        )

        schemas: list[dict[str, Any]] = []
        for tool in tools_to_export:
            schemas.append(
                {
                    "name": tool.metadata.name,
                    "description": tool.metadata.description,
                    "input_schema": tool.metadata.parameters,
                }
            )
        return schemas


# Global singleton registry
tool_registry = ToolRegistry()
