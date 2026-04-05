from typing import Any, Dict, Iterable, List

from src.schemas import ExecutionPlan, ExecutedAction


def make_agent_draft_action(action_id: str, summary: str, facts: Dict[str, Any]) -> ExecutedAction:
    return ExecutedAction(
        action_id=action_id,
        action_type="draft_reply",
        status="completed",
        summary=summary,
        output=facts,
    )


def completed_status(executed_actions: Iterable[ExecutedAction]) -> str:
    actions = list(executed_actions)
    if not actions:
        return "empty"
    if any(action.status in {"blocked", "failed"} for action in actions):
        return "partial"
    if any(action.status == "completed" for action in actions):
        return "completed"
    return "planned"


def secondary_routes(plan: ExecutionPlan) -> List[str]:
    return list(plan.secondary_routes or [])


def normalized_query(agent_input: Dict[str, Any]) -> str:
    parts = [
        agent_input.get("query", ""),
        agent_input.get("original_query", ""),
        agent_input.get("original_email_text", ""),
    ]
    return " ".join(part for part in parts if part).lower()


def has_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def append_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)
