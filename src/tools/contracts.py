from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.tools.models import ToolCapability, ToolRequest, ToolResult


@runtime_checkable
class ToolExecutor(Protocol):
    """Executable contract for one normalized tool capability."""

    def __call__(self, request: ToolRequest) -> ToolResult: ...


@runtime_checkable
class ToolLike(Protocol):
    """Object-oriented variant of a tool executor."""

    @property
    def capability(self) -> ToolCapability: ...

    def execute(self, request: ToolRequest) -> ToolResult: ...


@dataclass(slots=True)
class RegistryEntry:
    """Resolved registry record for one tool."""

    tool_name: str
    executor: ToolExecutor
    capability: ToolCapability | None = None
    family: str = ""
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
