from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import ObjectType
from src.objects.models import ResolvedObjectState
from src.routing.vocabulary import ActionType, DialogueActType


class _RoutingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogueActResult(_RoutingModel):
    """Dialogue act classification result (v3: inquiry / selection / closing)."""
    act: DialogueActType = "inquiry"
    is_continuation: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    matched_signals: list[str] = Field(default_factory=list)
    requires_active_object: bool = False
    selection_value: str = ""


class ExecutionObjectRef(_RoutingModel):
    """Internal routing type — also used by executor compat bridge."""
    object_type: ObjectType = "unknown"
    canonical_value: str = ""
    display_name: str = ""
    identifier: str = ""
    identifier_type: str = ""
    business_line: str = ""


class ExecutionAmbiguity(_RoutingModel):
    """Internal routing type — represents unresolved object ambiguity."""
    object_type: ObjectType = "unknown"
    query_value: str = ""
    candidate_refs: list[ExecutionObjectRef] = Field(default_factory=list)
    ambiguity_kind: str = ""
    clarification_focus: str = ""
    suggested_disambiguation_fields: list[str] = Field(default_factory=list)
    reason: str = ""


class ClarificationOption(_RoutingModel):
    label: str = ""
    value: str = ""


class ClarificationPayload(_RoutingModel):
    kind: str = "generic"
    reason: str = ""
    prompt: str = ""
    missing_information: list[str] = Field(default_factory=list)
    options: list[ClarificationOption] = Field(default_factory=list)


class RoutedObjectState(_RoutingModel):
    primary_object: ExecutionObjectRef | None = None
    active_object: ExecutionObjectRef | None = None
    secondary_objects: list[ExecutionObjectRef] = Field(default_factory=list)
    ambiguous_objects: list[ExecutionAmbiguity] = Field(default_factory=list)
    routing_status: str = "unresolved"
    should_block_execution: bool = False
    reason: str = ""


class RoutingInput(_RoutingModel):
    query: str = ""
    resolved_object_state: ResolvedObjectState
    risk_level: str = "low"
    needs_human_review: bool = False


class RouteDecision(_RoutingModel):
    """v3 output contract: replaces RoutingDecision + ExecutionIntent."""
    action: ActionType = "execute"
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    clarification: ClarificationPayload | None = None
    reason: str = ""
