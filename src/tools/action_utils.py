from typing import Any, Dict

from src.schemas import ExecutedAction


def make_blocked_action(
    *,
    action,
    action_type: str,
    summary: str,
    output: Dict[str, Any],
) -> ExecutedAction:
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action_type,
        status="blocked",
        summary=summary,
        output=output,
    )


def make_failed_action(
    *,
    action,
    action_type: str,
    summary: str,
    output: Dict[str, Any],
) -> ExecutedAction:
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action_type,
        status="failed",
        summary=summary,
        output=output,
    )
