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
from src.ingestion.models import ParserConstraints, ParserOpenSlots, ParserRequestFlags, ParserRetrievalHints
from src.memory.models import MemorySnapshot
from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult
from src.tools.models import ToolReadiness


class _ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Path evaluation models
# ---------------------------------------------------------------------------

class CandidatePath(_ExecutionModel):
    """A candidate execution path for a selected tool."""
    tool_name: str
    readiness: ToolReadiness
    selection_score: float = 0.0
    effective_priority: float = 0.0
    role: str = "primary"


class ClarificationFromPaths(_ExecutionModel):
    """Clarification info aggregated from blocked paths."""
    missing_by_path: dict[str, list[str]] = Field(default_factory=dict)
    # key = tool_name, value = list of missing identifier names


class PathEvaluation(_ExecutionModel):
    """Evaluation result for all candidate execution paths."""
    recommended_action: Literal["execute", "clarify"] = "execute"
    executable_paths: list[CandidatePath] = Field(default_factory=list)
    blocked_paths: list[CandidatePath] = Field(default_factory=list)
    clarification_context: ClarificationFromPaths | None = None


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
    parser_constraints: ParserConstraints | None = None
    parser_open_slots: ParserOpenSlots | None = None
    demand_profile: DemandProfile | None = None
    active_demand: GroupDemand | None = None
