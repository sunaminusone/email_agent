from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.routing.models import ExecutionIntent
from src.tools.models import ToolRequest, ToolResult


ExecutionMode = Literal["single", "sequential", "parallel"]
ExecutionStatus = Literal["ok", "partial", "empty", "error"]
ToolCallRole = Literal["primary", "supporting"]


class _ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannedToolCall(_ExecutionModel):
    call_id: str = ""
    tool_name: str
    request: ToolRequest
    role: ToolCallRole = "primary"
    priority: int = 0
    can_run_in_parallel: bool = False
    depends_on: list[str] = Field(default_factory=list)


class ExecutionPlan(_ExecutionModel):
    intent: ExecutionIntent
    planned_calls: list[PlannedToolCall] = Field(default_factory=list)
    execution_mode: ExecutionMode = "single"
    merge_policy: str = ""
    reason: str = ""


class ExecutedToolCall(_ExecutionModel):
    call_id: str = ""
    tool_name: str
    status: ExecutionStatus = "empty"
    request: ToolRequest
    result: ToolResult | None = None
    latency_ms: int = 0
    error: str = ""


class ExecutionRun(_ExecutionModel):
    intent: ExecutionIntent
    plan: ExecutionPlan
    executed_calls: list[ExecutedToolCall] = Field(default_factory=list)
    merged_results: dict[str, object] = Field(default_factory=dict)
    final_status: ExecutionStatus = "empty"
    reason: str = ""
