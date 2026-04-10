from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import ObjectRef


class _MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThreadMemory(_MemoryModel):
    thread_id: str | None = None
    active_route: str = ""
    continuity_mode: str = ""
    last_turn_type: str = ""
    last_user_goal: str = ""
    active_business_line: str = ""


class ObjectMemory(_MemoryModel):
    active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] = Field(default_factory=list)
    recent_objects: list[ObjectRef] = Field(default_factory=list)
    candidate_object_sets: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationMemory(_MemoryModel):
    pending_clarification_type: str = ""
    pending_candidate_options: list[str] = Field(default_factory=list)
    pending_identifier: str = ""
    pending_question: str = ""
    pending_route_after_clarification: str = ""


class ResponseMemory(_MemoryModel):
    revealed_attributes: list[str] = Field(default_factory=list)
    last_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    last_response_topics: list[str] = Field(default_factory=list)


class MemorySnapshot(_MemoryModel):
    thread_memory: ThreadMemory = Field(default_factory=ThreadMemory)
    object_memory: ObjectMemory = Field(default_factory=ObjectMemory)
    clarification_memory: ClarificationMemory = Field(default_factory=ClarificationMemory)
    response_memory: ResponseMemory = Field(default_factory=ResponseMemory)


class MemoryUpdate(_MemoryModel):
    active_object: ObjectRef | None = None
    secondary_active_objects: list[ObjectRef] = Field(default_factory=list)
    recent_objects: list[ObjectRef] = Field(default_factory=list)
    pending_clarification: ClarificationMemory | None = None
    response_memory: ResponseMemory | None = None
    route_updates: dict[str, Any] = Field(default_factory=dict)
    soft_reset_current_topic: bool = False
