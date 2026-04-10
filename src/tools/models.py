from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.models import ObjectType
from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult, DialogueActType, ModalityDecision, ModalityType


class _ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ToolConstraints(_ToolModel):
    common: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    tool: dict[str, Any] = Field(default_factory=dict)
    debug: dict[str, Any] = Field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ToolRequest(_ToolModel):
    tool_name: str
    query: str = ""
    primary_object: ObjectCandidate | None = None
    secondary_objects: list[ObjectCandidate] = Field(default_factory=list)
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    modality_decision: ModalityDecision = Field(default_factory=ModalityDecision)
    constraints: ToolConstraints = Field(default_factory=ToolConstraints)


class ToolResult(_ToolModel):
    tool_name: str
    status: str = "empty"
    primary_records: list[dict[str, Any]] = Field(default_factory=list)
    supporting_records: list[dict[str, Any]] = Field(default_factory=list)
    structured_facts: dict[str, Any] = Field(default_factory=dict)
    unstructured_snippets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    debug_info: dict[str, Any] = Field(default_factory=dict)


class ToolCapability(_ToolModel):
    tool_name: str
    supported_object_types: list[ObjectType] = Field(default_factory=list)
    supported_dialogue_acts: list[DialogueActType] = Field(default_factory=list)
    supported_modalities: list[ModalityType] = Field(default_factory=list)
    can_run_in_parallel: bool = False
    returns_structured_facts: bool = False
    returns_unstructured_snippets: bool = False
    requires_external_system: bool = False
