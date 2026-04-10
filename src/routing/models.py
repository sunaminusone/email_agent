from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.objects.models import AmbiguousObjectSet, ObjectCandidate


DialogueActType = Literal["INQUIRY", "SELECTION", "ACKNOWLEDGE", "TERMINATE", "ELABORATE", "UNKNOWN"]
ModalityType = Literal["structured_lookup", "unstructured_retrieval", "external_api", "hybrid", "unknown"]


class _RoutingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogueActResult(_RoutingModel):
    act: DialogueActType = "UNKNOWN"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    matched_signals: list[str] = Field(default_factory=list)
    requires_active_object: bool = False
    selection_value: str = ""


class ModalityDecision(_RoutingModel):
    primary_modality: ModalityType = "unknown"
    supporting_modalities: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    requires_structured_facts: bool = False
    requires_unstructured_context: bool = False
    requires_external_system: bool = False


class ExecutionIntent(_RoutingModel):
    primary_object: ObjectCandidate | None = None
    secondary_objects: list[ObjectCandidate] = Field(default_factory=list)
    ambiguous_sets: list[AmbiguousObjectSet] = Field(default_factory=list)
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    modality_decision: ModalityDecision = Field(default_factory=ModalityDecision)
    selected_tools: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    handoff_required: bool = False
    reason: str = ""
    resolved_object_constraints: dict[str, str] = Field(default_factory=dict)
