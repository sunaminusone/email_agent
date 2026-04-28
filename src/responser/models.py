from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import DemandProfile, SourceAttribution
from src.common.execution_models import ExecutionResult
from src.ingestion.models import ParserConstraints, ParserOpenSlots
from src.memory.models import MemoryUpdate, ResponseMemory
from src.objects.models import ResolvedObjectState
from src.routing.models import ClarificationPayload, DialogueActResult

if TYPE_CHECKING:
    from src.agent.state import GroupOutcome


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentBlock(_ResponseModel):
    block_type: str
    title: str = ""
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[SourceAttribution] = Field(default_factory=list)


class ResponseInput(_ResponseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    query: str = ""
    locale: str = "en"
    execution_result: ExecutionResult = Field(default_factory=ExecutionResult)
    resolved_object_state: ResolvedObjectState | None = None
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    response_memory: ResponseMemory | None = None
    action: Literal["execute", "respond", "clarify", "handoff"] = "execute"
    clarification: ClarificationPayload | None = None
    group_outcomes: list[Any] = Field(default_factory=list)  # list[GroupOutcome]
    demand_profile: DemandProfile | None = None
    parser_constraints: ParserConstraints | None = None
    parser_open_slots: ParserOpenSlots | None = None


class ResponsePlan(_ResponseModel):
    answer_focus: str = ""
    primary_content_blocks: list[ContentBlock] = Field(default_factory=list)
    supporting_content_blocks: list[ContentBlock] = Field(default_factory=list)
    should_acknowledge_object: bool = False
    memory_update: MemoryUpdate | None = None
    reason: str = ""


class ComposedResponse(_ResponseModel):
    message: str = ""
    response_type: str = ""
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    citations: list[SourceAttribution] = Field(default_factory=list)
    debug_info: dict[str, Any] = Field(default_factory=dict)


class ResponseBundle(_ResponseModel):
    composed_response: ComposedResponse
    response_plan: ResponsePlan
    response_topic: str = ""
    response_content_summary: str = ""
    response_path: str = "csr_renderer_direct"
