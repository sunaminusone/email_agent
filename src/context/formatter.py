from __future__ import annotations

import json
from typing import Any, Dict

from src.schemas import ExecutionRun, RouteDecision, RuntimeContext


def _pretty(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_routing_sections(runtime_context: RuntimeContext) -> Dict[str, str]:
    agent_context = runtime_context.agent_context
    state_payload = {
        "query": agent_context.query,
        "effective_query": agent_context.effective_query,
        "retrieval_query": agent_context.retrieval_query,
        "parsed_context": agent_context.context.model_dump(mode="json"),
        "routing_memory": agent_context.routing_memory.model_dump(mode="json"),
        "routing_signals": agent_context.routing_signals.model_dump(mode="json"),
        "turn_resolution": agent_context.turn_resolution.model_dump(mode="json"),
        "deterministic_payload": agent_context.deterministic_payload.model_dump(mode="json"),
        "interpreted_payload": agent_context.interpreted_payload.model_dump(mode="json"),
        "reference_resolution": agent_context.reference_resolution.model_dump(mode="json"),
        "session_payload": agent_context.session_payload.model_dump(mode="json"),
        "clarification_state": agent_context.clarification_state.model_dump(mode="json"),
        "user_preference": runtime_context.user_preference.model_dump(mode="json"),
        "attachments": agent_context.attachment_summary.model_dump(mode="json"),
    }
    history_payload = {
        "recent_summary": runtime_context.conversation_memory.recent_summary,
        "turns": [turn.model_dump(mode="json") for turn in runtime_context.conversation_memory.turns],
    }
    context_payload = {
        "knowledge_lookup_status": runtime_context.knowledge_context.lookup_status,
        "knowledge_snippets": [snippet.model_dump(mode="json") for snippet in runtime_context.knowledge_context.snippets],
    }
    instruction = (
        "Choose the best next route for this request. Use [State] for workflow status and known structured data, "
        "use [History] only for conversational continuity, and treat [Context] as retrieved reference material rather than user-confirmed facts."
    )
    return {
        "state_section": _pretty(state_payload),
        "history_section": _pretty(history_payload),
        "context_section": _pretty(context_payload),
        "instruction_section": instruction,
    }


def build_response_sections(
    runtime_context: RuntimeContext,
    route: RouteDecision,
    execution_run: ExecutionRun,
) -> Dict[str, str]:
    agent_context = runtime_context.agent_context
    state_payload = {
        "query": agent_context.query,
        "effective_query": agent_context.effective_query,
        "retrieval_query": agent_context.retrieval_query,
        "route_decision": route.model_dump(mode="json"),
        "routing_memory": agent_context.routing_memory.model_dump(mode="json"),
        "routing_debug": agent_context.routing_debug.model_dump(mode="json"),
        "turn_resolution": agent_context.turn_resolution.model_dump(mode="json"),
        "deterministic_payload": agent_context.deterministic_payload.model_dump(mode="json"),
        "interpreted_payload": agent_context.interpreted_payload.model_dump(mode="json"),
        "reference_resolution": agent_context.reference_resolution.model_dump(mode="json"),
        "session_payload": agent_context.session_payload.model_dump(mode="json"),
        "missing_information": agent_context.missing_information,
        "user_preference": runtime_context.user_preference.model_dump(mode="json"),
    }
    history_payload = {
        "recent_summary": runtime_context.conversation_memory.recent_summary,
        "turns": [turn.model_dump(mode="json") for turn in runtime_context.conversation_memory.turns],
    }
    context_payload = {
        "knowledge_lookup_status": runtime_context.knowledge_context.lookup_status,
        "knowledge_snippets": [snippet.model_dump(mode="json") for snippet in runtime_context.knowledge_context.snippets],
        "execution_results": [
            {
                "action_type": action.action_type,
                "status": action.status,
                "summary": action.summary,
                "output": action.output,
            }
            for action in execution_run.executed_actions
        ],
    }
    instruction = (
        "Write the next assistant reply. [State] contains the current workflow and user-specific structured signals, "
        "[History] contains prior dialogue, and [Context] contains retrieved references plus executed facts. "
        "Prefer executed tool results over generic retrieved context when they conflict."
    )
    return {
        "state_section": _pretty(state_payload),
        "history_section": _pretty(history_payload),
        "context_section": _pretty(context_payload),
        "instruction_section": instruction,
    }
