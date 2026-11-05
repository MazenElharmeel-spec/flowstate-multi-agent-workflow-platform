"""Shared MCP JSON-RPC 2.0 server protocol framework."""

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class MCPToolDef(BaseModel):
    name: str
    description: str
    inputSchema: dict[str, Any]
    side_effect: str = "read"
    risk: str = "low"
    requires_approval: bool = False
    idempotent: bool = True


class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: dict[str, MCPToolDef] = {}
        self.handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self.app = FastAPI(title=f"MCP Server - {name}", version=version)
        self._setup_routes()

    def register_tool(
        self,
        tool_def: MCPToolDef,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        self.tools[tool_def.name] = tool_def
        self.handlers[tool_def.name] = handler

    def _setup_routes(self) -> None:
        @self.app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "server": self.name, "version": self.version}

        @self.app.post("/mcp")
        async def handle_mcp(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    },
                    status_code=400,
                )

            req_id = body.get("id")
            method = body.get("method")
            params = body.get("params", {})

            if method == "initialize":
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": self.name, "version": self.version},
                        },
                    }
                )

            elif method == "tools/list":
                tools_list = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                        "metadata": {
                            "side_effect": t.side_effect,
                            "risk": t.risk,
                            "requires_approval": t.requires_approval,
                            "idempotent": t.idempotent,
                        },
                    }
                    for t in self.tools.values()
                ]
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}
                )

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if tool_name not in self.handlers:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method/Tool '{tool_name}' not found",
                            },
                        }
                    )

                handler = self.handlers[tool_name]
                try:
                    result_data = handler(arguments)
                    text_out = (
                        json.dumps(result_data) if not isinstance(result_data, str) else result_data
                    )
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [{"type": "text", "text": text_out}],
                                "isError": False,
                            },
                        }
                    )
                except Exception as exc:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [{"type": "text", "text": str(exc)}],
                                "isError": True,
                            },
                        }
                    )

            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown method '{method}'"},
                }
            )
