from __future__ import annotations

import logging

from src.response import run_response_pipeline
from src.schemas import FinalResponse, ExecutionRun, ResponseResolution, RouteDecision, RuntimeContext

from .response_resolution import resolve_response


logger = logging.getLogger(__name__)


def _safe_fallback(runtime_context: RuntimeContext, route: RouteDecision, execution_run: ExecutionRun) -> FinalResponse:
    agent_input = runtime_context.agent_context
    action_types = [
        action.action_type
        for action in execution_run.executed_actions
        if action.status != "pending"
    ]
    query = agent_input.query.strip()
    if agent_input.context.language == "zh":
        return FinalResponse(
            message=f"我已经处理了这个请求，当前路由为 {route.route_name}。如果你愿意，我可以继续围绕“{query}”补充下一步信息。",
            response_type="status_update",
            grounded_action_types=action_types,
        )
    return FinalResponse(
        message=f'I processed this request and routed it to {route.route_name}. We can continue from "{query}" with the grounded context already collected.',
        response_type="status_update",
        grounded_action_types=action_types,
    )


def build_response_artifacts(
    runtime_context: RuntimeContext,
    route: RouteDecision,
    execution_run: ExecutionRun,
) -> dict:
    response_resolution = resolve_response(runtime_context.agent_context, route, execution_run)
    artifacts = run_response_pipeline(
        {
            "runtime_context": runtime_context,
            "route": route,
            "execution_run": execution_run,
            "response_resolution": response_resolution,
        }
    )
    return {
        "final_response": artifacts["final_response"],
        "response_resolution": artifacts["response_resolution"],
        "response_topic": artifacts["topic_type"],
        "response_content_blocks": artifacts["content_blocks"],
        "response_content_summary": artifacts["content_summary"],
        "response_path": artifacts["response_path"],
        "legacy_fallback_used": artifacts["legacy_fallback_used"],
        "legacy_fallback_route": artifacts["legacy_fallback_route"],
        "legacy_fallback_responder": artifacts["legacy_fallback_responder"],
        "legacy_fallback_reason": artifacts["legacy_fallback_reason"],
    }


def generate_final_response(
    runtime_context: RuntimeContext,
    route: RouteDecision,
    execution_run: ExecutionRun,
) -> FinalResponse:
    try:
        artifacts = build_response_artifacts(runtime_context, route, execution_run)
        response = artifacts["final_response"]
        if isinstance(response, FinalResponse) and response.message.strip():
            return response
    except Exception:
        logger.exception("Response pipeline failed; falling back to safe response.")

    return _safe_fallback(runtime_context, route, execution_run)
