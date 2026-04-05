from __future__ import annotations

from src.context import build_response_sections


def preprocess_response_data(payload: dict) -> dict:
    runtime_context = payload["runtime_context"]
    route = payload["route"]
    execution_run = payload["execution_run"]
    agent_input = runtime_context.agent_context

    return {
        **payload,
        "agent_input": agent_input,
        "language": agent_input.context.language,
        "query": agent_input.query.strip(),
        "action_types": [
            action.action_type
            for action in execution_run.executed_actions
            if action.status != "pending"
        ],
        "response_sections": build_response_sections(runtime_context, route, execution_run),
    }
