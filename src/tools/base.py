from __future__ import annotations

from src.tools.models import ToolCapability, ToolRequest, ToolResult


class BaseTool:
    """Minimal base class for concrete tool implementations."""

    capability = ToolCapability(tool_name="")

    def __call__(self, request: ToolRequest) -> ToolResult:
        return self.execute(request)

    def execute(self, request: ToolRequest) -> ToolResult:
        raise NotImplementedError
