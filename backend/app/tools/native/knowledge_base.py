"""Native tool: search knowledge base policies and SLAs."""

from typing import Any

from backend.app.tools.base import BaseTool, ToolContext, ToolMetadata

KB_DOCUMENTS = [
    {
        "id": "kb-001",
        "topic": "refund_policy",
        "title": "Standard Customer Refund and Exchange Policy",
        "content": (
            "Refunds under $50 can be automatically approved by the system. "
            "Refunds between $50 and $200 require human manager sign-off. "
            "Refunds over $200 require director approval. "
            "Customers within 30 days of purchase are entitled to a full 100% refund or replacement. "
            "After 30 days, maximum 50% store credit or replacement is permitted."
        ),
    },
    {
        "id": "kb-002",
        "topic": "tier_sla",
        "title": "Customer Tier SLA & Priority Handling",
        "content": (
            "VIP customers (Tier 1) are entitled to immediate expedited refunds or replacements "
            "and a dedicated priority support escalation. Standard customers (Tier 2) receive "
            "resolution within 24 hours. Basic accounts (Tier 3) receive standard email resolutions."
        ),
    },
    {
        "id": "kb-003",
        "topic": "damaged_goods",
        "title": "Damaged In Transit or Defective Items",
        "content": (
            "If an item arrived damaged or defective with photo/carrier verification, "
            "the customer is entitled to an immediate replacement shipment or 100% refund, "
            "regardless of purchase date."
        ),
    },
]


class SearchKnowledgeBaseTool(BaseTool):
    metadata = ToolMetadata(
        name="search_knowledge_base",
        description="Search company policies, refund limits, SLA guidelines, and warranty terms.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or topic to search (e.g. 'refund policy', 'VIP tier')",
                }
            },
            "required": ["query"],
        },
        side_effect="read",
        risk="low",
        requires_approval=False,
        idempotent=True,
    )

    async def _execute(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> list[dict[str, Any]]:
        query = arguments["query"].lower()
        results: list[dict[str, Any]] = []

        for doc in KB_DOCUMENTS:
            if (
                query in doc["topic"].lower()
                or query in doc["title"].lower()
                or any(word in doc["content"].lower() for word in query.split())
            ):
                results.append(doc)

        return (
            results if results else KB_DOCUMENTS[:2]
        )  # Return default relevant policies if no direct keyword match
