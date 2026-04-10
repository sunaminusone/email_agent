from __future__ import annotations

from typing import Literal, TypeAlias


ToolStatus: TypeAlias = Literal["ok", "partial", "empty", "error"]
ToolHandlerName: TypeAlias = str
ToolFamily: TypeAlias = Literal["catalog", "documents", "rag", "quickbooks", "custom"]


DEFAULT_TOOL_STATUS: ToolStatus = "empty"
