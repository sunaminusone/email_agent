from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import ObjectRef
from src.memory.models import ClarificationMemory, MemoryContribution, MemorySnapshot
from src.common.models import ObjectType
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
    path_context: Any | None = None  # ClarificationFromPaths when from path evaluation


class RoutedObjectState(_RoutingModel):
    primary_object: ExecutionObjectRef | None = None
    active_object: ExecutionObjectRef | None = None
    secondary_objects: list[ExecutionObjectRef] = Field(default_factory=list)
    ambiguous_objects: list[ExecutionAmbiguity] = Field(default_factory=list)
    routing_status: str = "unresolved"
    should_block_execution: bool = False
    reason: str = ""



class RouteDecision(_RoutingModel):
    """v3 output contract: replaces RoutingDecision + ExecutionIntent."""
    action: ActionType = "execute"
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    clarification: ClarificationPayload | None = None
    reason: str = ""


def build_routing_memory_contribution(
    route: RouteDecision,
    current_snapshot: MemorySnapshot,
    active_object: ObjectRef | None,
    should_soft_reset: bool,
) -> MemoryContribution:
    clarification = route.clarification
    resume_route = (
        current_snapshot.thread_memory.active_route
        if current_snapshot.thread_memory.active_route
        and current_snapshot.thread_memory.active_route != "clarify"
        else "execute"
    )
    return MemoryContribution(
        source="routing",
        active_route=route.action,
        active_business_line=active_object.business_line if active_object is not None else "",
        set_pending_clarification=(
            ClarificationMemory(
                pending_clarification_type=clarification.kind,
                pending_candidate_options=[
                    option.label or option.value for option in clarification.options
                ],
                pending_identifier=(clarification.options[0].value if clarification.options else ""),
                pending_question=clarification.prompt,
                pending_route_after_clarification=resume_route,
            )
            if not should_soft_reset and clarification is not None
            else None
        ),
        clear_pending_clarification=should_soft_reset or clarification is None,
        reason=f"routing: action={route.action}",
    )
