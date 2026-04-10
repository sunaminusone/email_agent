from __future__ import annotations

from typing import Literal


DialogueActType = Literal[
    "INQUIRY",
    "SELECTION",
    "ACKNOWLEDGE",
    "TERMINATE",
    "ELABORATE",
    "UNKNOWN",
]

ModalityType = Literal[
    "structured_lookup",
    "unstructured_retrieval",
    "external_api",
    "hybrid",
    "unknown",
]

TopLevelRouteName = Literal["clarification", "execution", "handoff"]

ToolName = Literal[
    "catalog_lookup_tool",
    "technical_rag_tool",
    "document_lookup_tool",
    "pricing_lookup_tool",
    "order_lookup_tool",
    "shipping_lookup_tool",
    "invoice_lookup_tool",
    "customer_lookup_tool",
]


TECHNICAL_DEEP_DIVE_TERMS = {
    "mechanism",
    "pathway",
    "protocol",
    "troubleshoot",
    "why",
    "how",
    "validation",
    "validated",
    "experiment",
    "assay",
    "optimize",
    "optimization",
    "workflow",
    "rationale",
}

STRUCTURED_TERMS = {
    "price",
    "pricing",
    "quote",
    "availability",
    "catalog",
    "spec",
    "specification",
    "species",
    "application",
    "applications",
}

UNSTRUCTURED_TERMS = {
    *TECHNICAL_DEEP_DIVE_TERMS,
    "datasheet",
    "document",
    "documentation",
    "manual",
    "plan",
    "support",
    "overview",
}

EXTERNAL_TERMS = {
    "order",
    "invoice",
    "shipment",
    "shipping",
    "tracking",
    "customer",
    "delivery",
    "status",
    "balance",
}

