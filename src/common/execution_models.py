"""Execution output contracts — shared between executor and response layers.

These types define the executor's public output boundary. They live in
``src.common`` so that downstream consumers (response, app) can import
them without depending on the executor's internal implementation.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.tools.models import ToolRequest, ToolResult


ExecutionStatus = Literal["ok", "partial", "empty", "error"]
ToolCallRole = Literal["primary", "supporting"]


class _ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutedToolCall(_ExecutionModel):
    call_id: str = ""
    tool_name: str
    role: ToolCallRole = "primary"
    status: ExecutionStatus = "empty"
    request: ToolRequest
    result: ToolResult | None = None
    latency_ms: int = 0
    error: str = ""


class MergedResults(_ExecutionModel):
    """Typed container for aggregated tool results."""
    primary_facts: dict[str, Any] = Field(default_factory=dict)
    supporting_facts: dict[str, Any] = Field(default_factory=dict)
    snippets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionResult(_ExecutionModel):
    """Output contract of the executor layer."""
    executed_calls: list[ExecutedToolCall] = Field(default_factory=list)
    merged_results: MergedResults = Field(default_factory=MergedResults)
    final_status: ExecutionStatus = "empty"
    reason: str = ""
    iteration_count: int = 0
