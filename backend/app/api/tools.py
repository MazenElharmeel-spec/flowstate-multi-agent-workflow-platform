"""Tools catalog and metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_current_user
from backend.app.api.schemas import ToolDefinitionOut
from backend.app.db.models import User
from backend.app.tools.registry import tool_registry

router = APIRouter(prefix="/tools", tags=["Tools Registry"])


@router.get("", response_model=list[ToolDefinitionOut])
async def list_tools(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ToolDefinitionOut]:
    """Retrieve all registered tools with their schema, risk level, and approval requirements."""
    tools = tool_registry.list_tools()
    return [
        ToolDefinitionOut(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
            side_effect=t.side_effect,
            risk=t.risk,
            requires_approval=t.requires_approval,
            idempotent=t.idempotent,
            source=t.source,
            server_name=t.server_name,
        )
        for t in tools
    ]
