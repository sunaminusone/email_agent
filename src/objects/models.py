from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.ingestion.models import AttributeConstraint, EntitySpan, RecencyType, SourceType
from src.common.models import ObjectRef, ObjectType


class _ObjectsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectCandidate(ObjectRef):
    """Full object candidate — extends ObjectRef with resolution metadata.

    Shared fields (object_type, identifier, identifier_type, display_name,
    business_line) are inherited from ObjectRef.  ObjectCandidate IS-A
    ObjectRef, so it can be used wherever an ObjectRef is expected.
    """
    raw_value: str = ""
    canonical_value: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency: RecencyType = "CURRENT_TURN"
    source_type: SourceType = "parser"
    evidence_spans: list[EntitySpan] = Field(default_factory=list)
    attribute_constraints: list[AttributeConstraint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_ambiguous: bool = False
    used_stateful_anchor: bool = False


class AmbiguousObjectSet(_ObjectsModel):
    object_type: ObjectType = "unknown"
    query_value: str = ""
    candidates: list[ObjectCandidate] = Field(default_factory=list)
    ambiguity_kind: str = "generic"
    clarification_focus: str = ""
    suggested_disambiguation_fields: list[str] = Field(default_factory=list)
    resolution_strategy: str = "clarify"
    reason: str = ""
    attribute_constraints: list[AttributeConstraint] = Field(default_factory=list)


class ExtractorOutput(_ObjectsModel):
    candidates: list[ObjectCandidate] = Field(default_factory=list)
    ambiguous_sets: list[AmbiguousObjectSet] = Field(default_factory=list)


class ObjectBundle(_ObjectsModel):
    current_candidates: list[ObjectCandidate] = Field(default_factory=list)
    context_candidates: list[ObjectCandidate] = Field(default_factory=list)
    all_candidates: list[ObjectCandidate] = Field(default_factory=list)
    ambiguous_sets: list[AmbiguousObjectSet] = Field(default_factory=list)


class ResolvedObjectState(_ObjectsModel):
    primary_object: ObjectCandidate | None = None
    secondary_objects: list[ObjectCandidate] = Field(default_factory=list)
    ambiguous_sets: list[AmbiguousObjectSet] = Field(default_factory=list)
    active_object: ObjectCandidate | None = None
    used_stateful_anchor: bool = False
    resolution_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    resolution_reason: str = ""
    resolution_phase: str = ""
