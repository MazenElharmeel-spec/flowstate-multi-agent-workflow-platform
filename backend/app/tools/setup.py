"""Initialize and register native tools and MCP clients."""

from backend.app.core.config import get_settings
from backend.app.tools.mcp_client import MCPClient, mcp_manager
from backend.app.tools.native.calculator import CalculateRefundTool
from backend.app.tools.native.knowledge_base import SearchKnowledgeBaseTool
from backend.app.tools.registry import tool_registry

settings = get_settings()


def register_native_tools() -> None:
    tool_registry.register(SearchKnowledgeBaseTool())
    tool_registry.register(CalculateRefundTool())


def setup_mcp_clients() -> None:
    mcp_manager.register_client(MCPClient(server_name="crm-mcp", server_url=settings.CRM_MCP_URL))
    mcp_manager.register_client(
        MCPClient(server_name="ticketing-mcp", server_url=settings.TICKETING_MCP_URL)
    )
    mcp_manager.register_client(
        MCPClient(server_name="email-mcp", server_url=settings.EMAIL_MCP_URL)
    )
    mcp_manager.register_client(
        MCPClient(server_name="payments-mcp", server_url=settings.PAYMENTS_MCP_URL)
    )
