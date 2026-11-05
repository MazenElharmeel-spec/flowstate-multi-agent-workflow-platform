"""MCP Client and Proxy Layer with discovery, retries, timeouts, and graceful degradation."""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.app.core.errors import PermanentError, TransientError
from backend.app.tools.base import BaseTool, ToolContext, ToolMetadata
from backend.app.tools.registry import tool_registry

logger = logging.getLogger(__name__)


class MCPToolProxy(BaseTool):
    """Dynamically proxies tool calls over HTTP/MCP JSON-RPC to an external MCP server."""

    def __init__(self, metadata: ToolMetadata, server_url: str, client: "MCPClient"):
        self.metadata = metadata
        self.server_url = server_url
        self.client = client

    async def _execute(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        return await self.client.call_tool(
            self.metadata.name, arguments, timeout=self.metadata.timeout_seconds
        )


class MCPClient:
    def __init__(
        self,
        server_name: str,
        server_url: str,
        timeout_seconds: float = 10.0,
        app: Any | None = None,  # Optional ASGI app for direct in-process testing
    ):
        self.server_name = server_name
        self.server_url = server_url
        self.timeout_seconds = timeout_seconds
        self.app = app
        self._is_healthy = False
        self._last_checked: datetime | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self.app:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
                timeout=self.timeout_seconds,
            )
        return httpx.AsyncClient(
            base_url=self.server_url.rsplit("/", 1)[0],
            timeout=self.timeout_seconds,
        )

    async def check_health(self) -> bool:
        """Probe /health endpoint with timeout."""
        try:
            async with self._get_http_client() as client:
                res = await client.get("/health")
                self._is_healthy = res.status_code == 200
                self._last_checked = datetime.now(UTC)
                return self._is_healthy
        except Exception as exc:
            logger.warning("MCP server %s health check failed: %s", self.server_name, exc)
            self._is_healthy = False
            self._last_checked = datetime.now(UTC)
            return False

    async def discover_tools(self) -> list[ToolMetadata]:
        """Discover tools exposed by the MCP server via JSON-RPC tools/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        try:
            endpoint = "/mcp" if self.app else self.server_url
            async with self._get_http_client() as client:
                res = await client.post(endpoint, json=payload)
                if res.status_code != 200:
                    raise TransientError(
                        f"MCP server '{self.server_name}' returned status {res.status_code}"
                    )
                data = res.json()
                if "error" in data:
                    raise PermanentError(f"MCP server error: {data['error'].get('message')}")

                raw_tools = data.get("result", {}).get("tools", [])
                discovered: list[ToolMetadata] = []
                for t in raw_tools:
                    meta = t.get("metadata", {})
                    tool_meta = ToolMetadata(
                        name=t["name"],
                        description=t.get("description", ""),
                        parameters=t.get("inputSchema", {}),
                        side_effect=meta.get("side_effect", "read"),
                        risk=meta.get("risk", "low"),
                        requires_approval=meta.get("requires_approval", False),
                        idempotent=meta.get("idempotent", True),
                        source="mcp",
                        server_name=self.server_name,
                    )
                    discovered.append(tool_meta)
                self._is_healthy = True
                return discovered
        except (httpx.ConnectError, httpx.TimeoutException, TransientError) as exc:
            self._is_healthy = False
            raise TransientError(
                f"Failed to connect to MCP server '{self.server_name}': {str(exc)}"
            ) from exc

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> Any:
        """Call a tool on the MCP server with retry backoff and jitter."""
        payload = {
            "jsonrpc": "2.0",
            "id": random.randint(1000, 999999),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        attempt = 0
        endpoint = "/mcp" if self.app else self.server_url

        while attempt <= max_retries:
            try:
                async with self._get_http_client() as client:
                    res = await client.post(endpoint, json=payload, timeout=timeout)
                    if res.status_code >= 500:
                        raise TransientError(
                            f"Server error {res.status_code} from {self.server_name}"
                        )
                    if res.status_code != 200:
                        raise PermanentError(f"HTTP {res.status_code} calling tool '{tool_name}'")

                    body = res.json()
                    if "error" in body:
                        err = body["error"]
                        raise PermanentError(
                            f"MCP tool error ({err.get('code')}): {err.get('message')}"
                        )

                    result_obj = body.get("result", {})
                    if result_obj.get("isError"):
                        content = result_obj.get("content", [{}])[0].get("text", "Unknown error")
                        raise PermanentError(f"Tool execution failed: {content}")

                    # Extract content
                    content_list = result_obj.get("content", [])
                    if not content_list:
                        return None
                    first_text = content_list[0].get("text", "")
                    try:
                        return json.loads(first_text)
                    except json.JSONDecodeError:
                        return first_text

            except (httpx.ConnectError, httpx.TimeoutException, TransientError) as exc:
                attempt += 1
                if attempt > max_retries:
                    logger.error(
                        "MCP server '%s' exhausted retries on tool '%s': %s",
                        self.server_name,
                        tool_name,
                        exc,
                    )
                    raise TransientError(
                        f"MCP server '{self.server_name}' unreachable or timed out after {max_retries} retries: {str(exc)}"
                    ) from exc
                # Exponential backoff with jitter
                sleep_s = (1.5**attempt) + random.uniform(0.1, 0.4)
                await asyncio.sleep(sleep_s)


class MCPManager:
    def __init__(self) -> None:
        self.clients: dict[str, MCPClient] = {}

    def register_client(self, client: MCPClient) -> None:
        self.clients[client.server_name] = client

    async def initialize_all(self) -> dict[str, bool]:
        """Discovers tools on all registered MCP clients and mounts them in the global tool_registry."""
        status_map: dict[str, bool] = {}
        for name, client in self.clients.items():
            try:
                tools = await client.discover_tools()
                for tool_meta in tools:
                    proxy = MCPToolProxy(
                        metadata=tool_meta, server_url=client.server_url, client=client
                    )
                    tool_registry.register(proxy)
                status_map[name] = True
                logger.info("Successfully discovered %d tools from %s", len(tools), name)
            except Exception as exc:
                logger.warning("Could not initialize MCP server %s: %s", name, exc)
                status_map[name] = False
        return status_map


mcp_manager = MCPManager()
