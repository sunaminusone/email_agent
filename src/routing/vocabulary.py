from __future__ import annotations

from typing import Literal


# v3: 3 dialogue acts (inquiry, selection, closing)
DialogueActType = Literal["inquiry", "selection", "closing"]

# v3: 4 actions
ActionType = Literal["execute", "respond", "clarify", "handoff"]


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
