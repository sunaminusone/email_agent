from __future__ import annotations

from src.executor.engine import run_executor
from src.common.execution_models import (
    ExecutedToolCall,
    ExecutionResult,
)


def empty_execution_result(reason: str = "") -> ExecutionResult:
    """Create an empty ExecutionResult for non-execute routes (respond/clarify/handoff)."""
    return ExecutionResult(
        reason=reason or "No execution needed for this route action.",
    )


__all__ = [
    "ExecutedToolCall",
    "ExecutionResult",
    "empty_execution_result",
    "run_executor",
]
