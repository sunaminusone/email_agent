from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import DemandProfile, GroupDemand
from src.common.execution_models import (
    ExecutedToolCall as ExecutedToolCall,
    ExecutionResult as ExecutionResult,
    ExecutionStatus,
    MergedResults as MergedResults,
    ToolCallRole,
)
from src.ingestion.models import ParserRequestFlags, ParserRetrievalHints
from src.memory.models import MemorySnapshot
from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult


class _ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolSelection(_ExecutionModel):
    """A tool selected by the executor for dispatch."""
    tool_name: str
    match_score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    role: ToolCallRole = "primary"
    can_run_in_parallel: bool = False


class ExecutionContext(_ExecutionModel):
    """Internal state for a single executor pass."""
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # From upstream modules
    query: str = ""
    primary_intent: str = "unknown"
    primary_object: ObjectCandidate | None = None
    secondary_objects: list[ObjectCandidate] = Field(default_factory=list)
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    resolved_object_constraints: dict[str, str] = Field(default_factory=dict)
    memory_snapshot: MemorySnapshot | None = None

    # Ingestion signals
    request_flags: ParserRequestFlags | None = None
    retrieval_hints: ParserRetrievalHints | None = None
    demand_profile: DemandProfile | None = None
    active_demand: GroupDemand | None = None
