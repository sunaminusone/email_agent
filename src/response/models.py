from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import SourceAttribution
from src.execution.models import ExecutionRun
from src.memory.models import MemoryUpdate, ResponseMemory
from src.objects.models import ResolvedObjectState
from src.routing.models import DialogueActResult


ResponseMode = Literal[
    "clarification",
    "direct_answer",
    "hybrid_answer",
    "acknowledgement",
    "termination",
    "handoff",
]


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentBlock(_ResponseModel):
    block_type: str
    title: str = ""
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[SourceAttribution] = Field(default_factory=list)


class ResponseInput(_ResponseModel):
    query: str = ""
    execution_run: ExecutionRun
    resolved_object_state: ResolvedObjectState | None = None
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    response_memory: ResponseMemory | None = None


class ResponsePlan(_ResponseModel):
    response_mode: ResponseMode = "direct_answer"
    primary_content_blocks: list[ContentBlock] = Field(default_factory=list)
    supporting_content_blocks: list[ContentBlock] = Field(default_factory=list)
    should_use_llm_rewrite: bool = False
    should_acknowledge_object: bool = False
    memory_update: MemoryUpdate | None = None
    reason: str = ""


class ComposedResponse(_ResponseModel):
    message: str = ""
    response_type: str = ""
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    citations: list[SourceAttribution] = Field(default_factory=list)
    debug_info: dict[str, Any] = Field(default_factory=dict)
