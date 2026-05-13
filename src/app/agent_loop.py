from __future__ import annotations

import logging

from src.agent.state import AgentState
from src.common.execution_models import ExecutionResult
from src.common.models import DemandProfile, IntentGroup
from src.executor import empty_execution_result, run_executor
from src.ingestion.demand_profile import narrow_demand_profile
from src.memory.models import MemoryContext
from src.routing import route


logger = logging.getLogger(__name__)


def _extract_rag_confidence(execution_result: ExecutionResult) -> dict[str, object] | None:
    """Pull retrieval_confidence off the first technical_rag_tool call, if any."""
    for call in execution_result.executed_calls:
        if call.tool_name != "technical_rag_tool" or call.result is None:
            continue
        confidence = call.result.structured_facts.get("retrieval_confidence")
        if confidence:
            return dict(confidence)
    return None


def _coerce_route_for_csr(route_decision):
    """Convert non-execute routing decisions into CSR advisory execute flow."""
    if route_decision.action == "execute":
        return route_decision

    note_parts = [f"AI_ROUTING_NOTE original_action={route_decision.action}"]
    if route_decision.reason:
        note_parts.append(route_decision.reason)
    if route_decision.clarification and route_decision.clarification.reason:
        note_parts.append(
            f"clarification_reason={route_decision.clarification.reason}"
        )
    return route_decision.model_copy(
        update={
            "action": "execute",
            "reason": " | ".join(note_parts),
        }
    )


def _run_group_execution(
    *,
    ingestion_bundle,
    resolved_object_state,
    memory_context: MemoryContext,
    demand_profile: DemandProfile,
    group,
    scoped_demand,
    route_decision,
    tool_call_cache,
):
    """Evaluate execution paths for one intent group and run the chosen path."""
    from src.executor.engine import build_execution_context, extract_available_params
    from src.executor.path_evaluation import (
        evaluate_execution_paths,
        find_resolution_provider,
    )
    from src.executor.tool_selector import select_tools
    from src.routing.models import ClarificationPayload

    if route_decision.action != "execute":
        execution_result = empty_execution_result(
            reason=f"No execution needed: action={route_decision.action}",
        )
        return route_decision, execution_result, "resolved"

    context = build_execution_context(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved_object_state,
        route_decision=route_decision,
        memory_snapshot=memory_context.snapshot,
        focus_group=group,
        demand_profile=demand_profile,
        tool_call_cache=tool_call_cache,
        active_demand=scoped_demand,
    )

    selections = select_tools(context)
    available_params = extract_available_params(
        context, tool_call_cache=tool_call_cache
    )
    obj_type = context.primary_object.object_type if context.primary_object else ""
    path_eval = evaluate_execution_paths(selections, obj_type, available_params)

    if path_eval.recommended_action == "execute":
        execution_result = run_executor(
            ingestion_bundle=ingestion_bundle,
            resolved_object_state=resolved_object_state,
            route_decision=route_decision,
            memory_snapshot=memory_context.snapshot,
            focus_group=group,
            demand_profile=demand_profile,
            tool_call_cache=tool_call_cache,
            active_demand=scoped_demand,
        )
        any_successful_call = any(
            call.status in ("ok", "partial")
            for call in execution_result.executed_calls
        )
        status = (
            "resolved"
            if execution_result.final_status in ("ok", "partial")
            or any_successful_call
            else "needs_clarification"
        )
        return route_decision, execution_result, status

    provider = find_resolution_provider(path_eval, available_params)
    if provider is not None:
        execution_result = run_executor(
            ingestion_bundle=ingestion_bundle,
            resolved_object_state=resolved_object_state,
            route_decision=route_decision,
            memory_snapshot=memory_context.snapshot,
            focus_group=group,
            demand_profile=demand_profile,
            tool_call_cache=tool_call_cache,
            active_demand=scoped_demand,
        )
        status = (
            "resolved"
            if execution_result.final_status in ("ok", "partial")
            else "needs_clarification"
        )
        return route_decision, execution_result, status

    execution_result = empty_execution_result(
        reason="all execution paths insufficient",
    )
    if path_eval.clarification_context is not None:
        missing_info: list[str] = []
        for ids_list in path_eval.clarification_context.missing_by_path.values():
            for identifier in ids_list:
                if identifier not in missing_info:
                    missing_info.append(identifier)
        route_decision = route_decision.model_copy(
            update={
                "action": "clarify",
                "clarification": ClarificationPayload(
                    kind="path_evaluation",
                    reason="All candidate execution paths are insufficient.",
                    missing_information=missing_info,
                    path_context=path_eval.clarification_context,
                ),
            }
        )
    else:
        route_decision = route_decision.model_copy(
            update={
                "action": "clarify",
            }
        )
    return route_decision, execution_result, "needs_clarification"


def _log_group_retrieval_confidence(
    *,
    thread_id: str,
    route_decision,
    execution_result: ExecutionResult,
) -> None:
    """Emit telemetry for retrieval confidence on execute-path groups."""
    if route_decision.action != "execute":
        return

    rag_confidence = _extract_rag_confidence(execution_result)
    if rag_confidence is not None:
        logger.info(
            "rag_confidence thread=%s confidence=%s",
            thread_id,
            rag_confidence,
        )


def _record_group_outcome(
    *,
    agent_state: AgentState,
    group,
    route_decision,
    execution_result: ExecutionResult,
    status: str,
    scoped_demand,
) -> None:
    """Persist one group outcome onto the running agent state."""
    agent_state.record(
        group,
        route_decision,
        execution_result,
        status=status,
        scoped_demand=scoped_demand,
    )


def _run_agent_loop(
    intent_groups: list[IntentGroup],
    demand_profile: DemandProfile,
    ingestion_bundle,
    resolved_object_state,
    memory_context: MemoryContext,
) -> AgentState:
    """Iterate over intent groups, route and execute each independently."""
    from src.agent.tool_call_cache import ToolCallCache

    agent_state = AgentState()
    cache = ToolCallCache()

    for group in intent_groups:
        scoped_demand = narrow_demand_profile(
            demand_profile,
            group,
            prior_demand_type=memory_context.prior_demand_type,
            prior_demand_flags=memory_context.prior_demand_flags,
            continuity_confidence=memory_context.intent_continuity_confidence,
        )

        route_decision = route(
            ingestion_bundle,
            resolved_object_state,
            focus_group=group,
            scoped_demand=scoped_demand,
        )
        route_decision = _coerce_route_for_csr(route_decision)
        route_decision, execution_result, status = _run_group_execution(
            ingestion_bundle=ingestion_bundle,
            resolved_object_state=resolved_object_state,
            memory_context=memory_context,
            demand_profile=demand_profile,
            group=group,
            scoped_demand=scoped_demand,
            route_decision=route_decision,
            tool_call_cache=cache,
        )
        _log_group_retrieval_confidence(
            thread_id=ingestion_bundle.turn_core.thread_id,
            route_decision=route_decision,
            execution_result=execution_result,
        )
        _record_group_outcome(
            agent_state=agent_state,
            group=group,
            route_decision=route_decision,
            execution_result=execution_result,
            status=status,
            scoped_demand=scoped_demand,
        )

    return agent_state
