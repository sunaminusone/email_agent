from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RecencyType = Literal["CURRENT_TURN", "CONTEXTUAL"]
SourceType = Literal[
    "parser",
    "deterministic",
    "stateful_anchor",
    "attachment",
    "registry",
    "tool",
    "memory",
    "system",
]
ObjectType = Literal[
    "product",
    "service",
    "order",
    "invoice",
    "shipment",
    "document",
    "customer",
    "scientific_target",
    "unknown",
]
DemandType = Literal[
    "technical",
    "commercial",
    "operational",
    "general",
]


class _CommonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfidenceScore(_CommonModel):
    value: float = Field(default=0.0, ge=0.0, le=1.0)


class SourceAttribution(_CommonModel):
    source_type: SourceType = "system"
    recency: RecencyType = "CURRENT_TURN"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_label: str = ""


class ValueSignal(_CommonModel):
    value: str = ""
    raw: str = ""
    normalized_value: str | None = None
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class EntitySpan(_CommonModel):
    text: str
    raw: str = ""
    start: int = Field(default=-1, ge=-1)
    end: int = Field(default=-1, ge=-1)
    normalized_value: str | None = None
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class TimeRange(_CommonModel):
    start_text: str | None = None
    end_text: str | None = None
    raw: str = ""
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class AttributeConstraint(_CommonModel):
    attribute: str
    operator: str = "equals"
    value: str
    raw: str = ""
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class ObjectRef(_CommonModel):
    object_type: ObjectType = "unknown"
    identifier: str = ""
    identifier_type: str = ""
    display_name: str = ""
    business_line: str = ""
    turn_age: int = 0
    interaction_count: int = 1


class IntentGroup(_CommonModel):
    """One coherent user need, bound to a resolved object."""
    intent: str = "unknown"
    request_flags: list[str] = Field(default_factory=list)
    object_type: str = ""
    object_identifier: str = ""
    object_display_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class GroupDemand(_CommonModel):
    """Demand classification for one intent group.

    demand_confidence measures how certain we are about the *demand
    classification* itself — NOT about object binding.  It is computed
    from the strength of the signals that produced the demand:

    - 0.9: explicit flags active (strongest signal)
    - 0.7: no flags, but intent maps to a non-general demand type
    - 0.4: no flags, general/unknown intent (weak signal)
    """
    intent: str = "unknown"
    primary_demand: DemandType = "general"
    secondary_demands: list[DemandType] = Field(default_factory=list)
    request_flags: list[str] = Field(default_factory=list)
    object_type: str = ""
    object_identifier: str = ""
    object_display_name: str = ""
    demand_confidence: float = Field(default=0.4, ge=0.0, le=1.0)


class DemandProfile(_CommonModel):
    """Shared semantic contract describing the user's information demand."""
    primary_demand: DemandType = "general"
    secondary_demands: list[DemandType] = Field(default_factory=list)
    active_request_flags: list[str] = Field(default_factory=list)
    group_demands: list[GroupDemand] = Field(default_factory=list)
    reason: str = ""
