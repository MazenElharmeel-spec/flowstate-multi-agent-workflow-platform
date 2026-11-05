"""Base classes, metadata models, and validation for native and MCP tools."""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, Field

from backend.app.core.errors import PermanentError, TransientError


class ToolMetadata(BaseModel):
    name: str = Field(..., description="Unique tool identifier")
    description: str = Field(..., description="Description for LLM tool selection")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for input parameters"
    )
    side_effect: Literal["read", "write"] = Field(
        default="read", description="Whether tool alters external state"
    )
    risk: Literal["low", "medium", "high"] = Field(
        default="low", description="Risk assessment level"
    )
    requires_approval: bool = Field(
        default=False, description="Whether human approval is required by default"
    )
    idempotent: bool = Field(
        default=True, description="Whether repeated calls with same args are safe"
    )
    timeout_seconds: float = Field(default=30.0, description="Tool execution timeout in seconds")
    max_retries: int = Field(default=2, description="Maximum retries for transient errors")
    backoff_factor: float = Field(default=1.5, description="Exponential backoff multiplier")
    source: Literal["native", "mcp"] = Field(
        default="native", description="Source of the tool implementation"
    )
    server_name: str | None = Field(default=None, description="MCP server name if applicable")


@dataclass
class ToolContext:
    run_id: str
    step_index: int
    actor_agent: str
    idempotency_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_name: str
    status: Literal["success", "error"]
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    is_transient: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_safe_prompt_context(self, max_length: int = 4000) -> str:
        """Format the result as explicitly delimited, untrusted external text for LLM consumption.

        Hardens against prompt injection by clearly sandboxing output.
        """
        raw_text = (
            json.dumps(self.data, default=str) if not isinstance(self.data, str) else self.data
        )
        if len(raw_text) > max_length:
            raw_text = raw_text[:max_length] + "\n[OUTPUT TRUNCATED DUE TO SIZE LIMIT]"

        return (
            f"=== BEGIN UNTRUSTED EXTERNAL DATA FROM TOOL '{self.tool_name}' ===\n"
            f"STATUS: {self.status.upper()}\n"
            f"CONTENT:\n{raw_text}\n"
            f"=== END UNTRUSTED EXTERNAL DATA FROM TOOL '{self.tool_name}' ==="
        )


class BaseTool(ABC):
    """Abstract Base Class for all workflow tools."""

    metadata: ToolMetadata

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        """Validate input arguments against tool's JSON schema."""
        if not self.metadata.parameters:
            return
        try:
            jsonschema.validate(instance=arguments, schema=self.metadata.parameters)
        except jsonschema.ValidationError as err:
            raise PermanentError(
                f"Validation error for tool '{self.metadata.name}': {err.message}",
                details={"param": err.path, "schema_error": err.message},
            ) from err

    async def run(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Executes the tool with validation, timing, and error classification."""
        self.validate_arguments(arguments)
        start_time = time.perf_counter()
        try:
            data = await self._execute(arguments, context)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                tool_name=self.metadata.name,
                status="success",
                data=data,
                duration_ms=duration_ms,
            )
        except (TransientError, TimeoutError, ConnectionError) as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                tool_name=self.metadata.name,
                status="error",
                error=str(exc),
                duration_ms=duration_ms,
                is_transient=True,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                tool_name=self.metadata.name,
                status="error",
                error=str(exc),
                duration_ms=duration_ms,
                is_transient=False,
            )

    @abstractmethod
    async def _execute(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        """Implement tool-specific execution logic."""
        pass
