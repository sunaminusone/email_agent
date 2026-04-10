from __future__ import annotations


class ToolError(Exception):
    """Base exception for tool-layer failures."""


class ToolRegistrationError(ToolError):
    """Raised when a tool cannot be registered safely."""


class UnknownToolError(ToolError):
    """Raised when a requested tool is not present in the registry."""


class ToolExecutionError(ToolError):
    """Raised when a tool executor fails during dispatch."""
