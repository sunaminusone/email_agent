from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from src.tools.models import ToolCapability, ToolRequest, ToolResult


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ToolStatus: TypeAlias = Literal["ok", "partial", "empty", "error"]


# ---------------------------------------------------------------------------
# Protocols & base class
# ---------------------------------------------------------------------------

@runtime_checkable
class ToolExecutor(Protocol):
    """Executable contract for one normalized tool capability."""

    def __call__(self, request: ToolRequest) -> ToolResult: ...


class BaseTool:
    """Minimal base class for concrete tool implementations."""

    capability = ToolCapability(tool_name="")

    def __call__(self, request: ToolRequest) -> ToolResult:
        return self.execute(request)

    def execute(self, request: ToolRequest) -> ToolResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RegistryEntry:
    """Resolved registry record for one tool."""

    tool_name: str
    executor: ToolExecutor
    capability: ToolCapability | None = None
    family: str = ""
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """Base exception for tool-layer failures."""


class ToolRegistrationError(ToolError):
    """Raised when a tool cannot be registered safely."""


class UnknownToolError(ToolError):
    """Raised when a requested tool is not present in the registry."""


class ToolExecutionError(ToolError):
    """Raised when a tool executor fails during dispatch."""
