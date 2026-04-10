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
