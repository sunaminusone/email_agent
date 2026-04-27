from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.state import AgentState
from src.api_models import AgentPrototypeResponse, AgentRequest, FinalResponsePayload
from src.common.messages import get_message
from src.common.models import DemandProfile, IntentGroup, ObjectRef
from src.executor import empty_execution_result, run_executor
from src.common.execution_models import ExecutionResult
from src.ingestion import build_demand_profile
from src.routing.intent_assembly import assemble_intent_groups
from src.ingestion.demand_profile import narrow_demand_profile
from src.ingestion.pipeline import build_ingestion_bundle
from src.memory import (
    SessionStore,
    serialize_memory_snapshot,
    snapshot_to_route_state,
    recall,
    reflect,
    MemoryContribution,
)
from src.memory.models import ClarificationMemory, MemoryContext
from src.objects.models import ObjectCandidate
from src.objects.resolution import resolve_objects
from src.responser import ResponseInput, build_response_bundle
from src.routing import route


logger = logging.getLogger(__name__)

# RAG confidence levels are now tiered (low/medium/high) using thresholds
# derived from synthetic corpora. The gate stays disabled until real traffic
# validates those cutoffs and the action target ("handoff" vs "clarify")
# is reconciled with the backlog.
_RAG_CONFIDENCE_HANDOFF_ENABLED = False


def _extract_rag_confidence(execution_result: ExecutionResult) -> dict[str, Any] | None:
    """Pull retrieval_confidence off the first technical_rag_tool call, if any."""
    for call in execution_result.executed_calls:
        if call.tool_name != "technical_rag_tool" or call.result is None:
            continue
        confidence = call.result.structured_facts.get("retrieval_confidence")
        if confidence:
            return dict(confidence)
    return None


def _message_signature(message: dict[str, Any]) -> tuple[str, str, str]:
    metadata = message.get("metadata", {}) or {}
    return (
        str(message.get("role", "user")),
        str(message.get("content", "")),
        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


def _merge_histories(
    persisted_history: list[dict[str, Any]],
    request_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for message in [*persisted_history, *request_history]:
        signature = _message_signature(message)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(message)

    return merged


def _tool_action_type(tool_name: str) -> str:
    return {
        "catalog_lookup_tool": "lookup_catalog_product",
        "pricing_lookup_tool": "lookup_price",
        "document_lookup_tool": "lookup_document",
        "technical_rag_tool": "retrieve_technical_knowledge",
        "customer_lookup_tool": "lookup_customer",
        "invoice_lookup_tool": "lookup_invoice",
        "order_lookup_tool": "lookup_order",
        "shipping_lookup_tool": "lookup_shipping",
    }.get(tool_name, tool_name)


def _extract_output_payload(result: Any | None) -> dict[str, Any]:
    if result is None:
        return {}
    output = dict(result.structured_facts)
    if result.primary_records:
        output.setdefault("matches", list(result.primary_records))
    if result.supporting_records:
        output.setdefault("supporting_matches", list(result.supporting_records))
    if result.artifacts:
        output.setdefault("artifacts", list(result.artifacts))
    if result.unstructured_snippets:
        output.setdefault("snippets", list(result.unstructured_snippets))
    return output


def _serialize_execution_plan(result: ExecutionResult) -> dict[str, Any]:
    """Serialize ExecutionResult into the plan payload for the frontend."""
    return {
        "planned_actions": [
            {
                "action_id": call.call_id,
                "action_type": _tool_action_type(call.tool_name),
                "tool_name": call.tool_name,
                "role": call.role,
            }
            for call in result.executed_calls
        ],
        "iterations": 1,
        "reason": result.reason,
    }


def _serialize_execution_run(result: ExecutionResult) -> dict[str, Any]:
    """Serialize ExecutionResult into the run payload for the frontend."""
    payload = result.model_dump(mode="json")
    payload["executed_actions"] = [
        {
            "action_id": call.call_id,
            "action_type": _tool_action_type(call.tool_name),
            "tool_name": call.tool_name,
            "status": call.status,
            "summary": call.result.debug_info.get("summary", "") if call.result is not None else "",
            "output": _extract_output_payload(call.result),
            "latency_ms": call.latency_ms,
            "error": call.error,
        }
        for call in result.executed_calls
    ]
    payload["overall_status"] = result.final_status
    return payload


def _serialize_content_blocks(content_blocks) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for block in content_blocks:
        payload = block.model_dump(mode="json")
        payload.setdefault("kind", payload.get("block_type", ""))
        payload.setdefault("text", payload.get("body", ""))
        serialized.append(payload)
    return serialized


def _build_reply_preview(query: str, overall_action: str, execution_run_payload: dict[str, Any], final_response: FinalResponsePayload, *, locale: str = "zh") -> str:
    if final_response.message:
        return final_response.message
    if overall_action == "clarify":
        return get_message("reply_preview_clarify", locale, query=query)
    if overall_action == "handoff":
        return get_message("reply_preview_handoff", locale, query=query)
    action_count = len(execution_run_payload.get("executed_actions", []))
    return get_message("reply_preview_done", locale, query=query, action_count=action_count)


def _to_object_ref(candidate: ObjectCandidate | None) -> ObjectRef | None:
    """Convert ObjectCandidate → ObjectRef, stripping resolution metadata.

    ObjectCandidate IS-A ObjectRef, but memory/response layers should
    store the lightweight ObjectRef to avoid carrying evidence_spans,
    attribute_constraints, etc.
    """
    if candidate is None:
        return None
    return ObjectRef(
        object_type=candidate.object_type,
        identifier=candidate.identifier,
        identifier_type=candidate.identifier_type,
        display_name=candidate.display_name or candidate.canonical_value,
        business_line=candidate.business_line,
    )


def _build_objects_contribution(
    resolved_object_state,
    should_soft_reset: bool,
) -> MemoryContribution:
    active_object = (
        None if should_soft_reset
        else (resolved_object_state.primary_object or resolved_object_state.active_object)
    )
    recent_objects = [
        item
        for item in [
            _to_object_ref(resolved_object_state.primary_object),
            _to_object_ref(resolved_object_state.active_object),
            *[_to_object_ref(obj) for obj in resolved_object_state.secondary_objects],
        ]
        if item is not None
    ]
    return MemoryContribution(
        source="objects",
        set_active_object=_to_object_ref(active_object),
        secondary_active_objects=[
            item
            for item in (_to_object_ref(obj) for obj in resolved_object_state.secondary_objects)
            if item is not None
        ],
        append_recent_objects=recent_objects,
        soft_reset_current_topic=should_soft_reset,
        reason="objects: resolved from current turn",
    )


def _build_ingestion_contribution(
    intent_groups: list[IntentGroup],
) -> MemoryContribution:
    return MemoryContribution(
        source="ingestion",
        intent_groups=list(intent_groups),
        reason=f"ingestion: assembled {len(intent_groups)} intent group(s)",
    )


def _build_routing_contribution(
    route,
    current_snapshot,
    final_response: FinalResponsePayload,
    active_object: ObjectRef | None,
    should_soft_reset: bool,
) -> MemoryContribution:
    clarification = route.clarification
    resume_route = (
        current_snapshot.thread_memory.active_route
        if current_snapshot.thread_memory.active_route and current_snapshot.thread_memory.active_route != "clarify"
        else "execute"
    )
    return MemoryContribution(
        source="routing",
        active_route=route.action,
        route_phase="waiting_for_user" if final_response.response_type == "clarification" else "active",
        active_business_line=getattr(active_object, "business_line", "") if active_object is not None else "",
        set_pending_clarification=(
            ClarificationMemory(
                pending_clarification_type=clarification.kind,
                pending_candidate_options=[option.label or option.value for option in clarification.options],
                pending_identifier=(clarification.options[0].value if clarification.options else ""),
                pending_question=clarification.prompt,
                pending_route_after_clarification=resume_route,
            )
            if not should_soft_reset and clarification is not None
            else None
        ),
        clear_pending_clarification=should_soft_reset or clarification is None,
        reason=f"routing: action={route.action}",
    )


def _build_response_contribution(
    response_plan,
) -> MemoryContribution:
    if response_plan is None or response_plan.memory_update is None:
        return MemoryContribution(source="response", reason="response: no memory update")

    mu = response_plan.memory_update
    return MemoryContribution(
        source="response",
        mark_revealed_attributes=(
            list(mu.response_memory.revealed_attributes) if mu.response_memory else None
        ),
        set_last_tool_results=(
            list(mu.response_memory.last_tool_results) if mu.response_memory else None
        ),
        set_last_response_topics=(
            list(mu.response_memory.last_response_topics) if mu.response_memory else None
        ),
        set_last_demand_type=(
            mu.response_memory.last_demand_type if mu.response_memory else None
        ),
        set_last_demand_flags=(
            list(mu.response_memory.last_demand_flags) if mu.response_memory else None
        ),
        soft_reset_current_topic=mu.soft_reset_current_topic,
        reason=mu.reason or "response: plan applied",
    )


def _build_agent_input_payload(
    ingestion_bundle,
    resolved_object_state,
    agent_state: AgentState,
    demand_profile: DemandProfile | None,
) -> dict[str, Any]:
    parser_context = ingestion_bundle.turn_signals.parser_signals.context
    primary_object = resolved_object_state.primary_object or resolved_object_state.active_object
    primary_label = ""
    primary_type = ""
    if primary_object is not None:
        primary_label = (
            primary_object.canonical_value
            or primary_object.display_name
            or primary_object.identifier
            or ""
        )
        primary_type = primary_object.object_type
    route_decision = agent_state.primary_route_decision
    clarification = agent_state.primary_clarification
    return {
        "thread_id": ingestion_bundle.turn_core.thread_id,
        "query": ingestion_bundle.turn_core.normalized_query,
        "raw_query": ingestion_bundle.turn_core.raw_query,
        "semantic_intent": parser_context.semantic_intent,
        "missing_information": (
            list(clarification.missing_information)
            if clarification is not None
            else list(ingestion_bundle.turn_signals.parser_signals.missing_information)
        ),
        "active_service_name": primary_label if primary_type == "service" else "",
        "active_product_name": primary_label if primary_type == "product" else "",
        "active_target": primary_label if primary_type == "scientific_target" else "",
        "resolved_object_state": resolved_object_state.model_dump(mode="json"),
        "routing_debug": {
            "action": agent_state.overall_action,
            "dialogue_act": route_decision.dialogue_act.act,
            "dialogue_act_confidence": route_decision.dialogue_act.confidence,
            "intent": parser_context.semantic_intent,
            "intent_confidence": parser_context.intent_confidence,
            "business_line": getattr(primary_object, "business_line", "") if primary_object is not None else "",
            "business_line_confidence": resolved_object_state.resolution_confidence,
            "has_clarification": clarification is not None,
        },
        "agent_debug": agent_state.debug_summary(),
        "semantic_debug": (
            demand_profile.model_dump(mode="json")
            if demand_profile is not None
            else {}
        ),
    }


def _build_suggested_workflow(overall_action: str, execution_plan_payload: dict[str, Any], *, locale: str = "zh") -> list[str]:
    m = lambda key, **kw: get_message(key, locale, **kw)
    workflow = [
        m("workflow_parse_input"),
        m("workflow_extract_objects"),
        m("workflow_route"),
    ]
    if overall_action == "clarify":
        workflow.append(m("workflow_clarify"))
        return workflow
    if overall_action == "handoff":
        workflow.append(m("workflow_handoff"))
        return workflow
    if overall_action == "respond":
        workflow.append(m("workflow_respond"))
        return workflow

    planned_actions = execution_plan_payload.get("planned_actions", [])
    if planned_actions:
        workflow.extend([m("workflow_execute_tool", action_type=action["action_type"]) for action in planned_actions])
    workflow.append(m("workflow_draft_reply"))
    return workflow


def _load_session_context(request: AgentRequest):
    session_store = SessionStore()
    session = session_store.load_session(request.thread_id)
    memory_snapshot = session_store.load_memory_snapshot(request.thread_id)
    persisted_history = session.get("recent_turns", [])
    request_history = [msg.model_dump(mode="json") for msg in request.conversation_history]
    merged_history = _merge_histories(persisted_history, request_history)
    attachments = [att.model_dump(mode="json") for att in request.attachments]
    return session_store, memory_snapshot, merged_history, attachments


def _build_final_response_payload(agent_state: AgentState, execution_result: ExecutionResult, response_bundle) -> FinalResponsePayload:
    clarification = agent_state.primary_clarification
    return FinalResponsePayload(
        message=response_bundle.composed_response.message,
        response_type=response_bundle.composed_response.response_type,
        grounded_action_types=[
            _tool_action_type(call.tool_name)
            for call in execution_result.executed_calls
            if call.status != "error"
        ],
        needs_human_handoff=response_bundle.composed_response.response_type == "handoff",
        missing_information_requested=(
            list(clarification.missing_information)
            if clarification is not None
            else []
        ),
    )


def _persist_session_state(
    session_store: SessionStore,
    thread_id: str,
    user_query: str,
    memory_context: MemoryContext,
    ingestion_bundle,
    resolved_object_state,
    intent_groups: list[IntentGroup],
    demand_profile: DemandProfile,
    agent_state: AgentState,
    final_response: FinalResponsePayload,
    response_bundle,
    reply_preview: str,
    response_content_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    should_soft_reset = bool(
        response_bundle.response_plan is not None
        and response_bundle.response_plan.memory_update is not None
        and response_bundle.response_plan.memory_update.soft_reset_current_topic
    )
    active_object = (
        None if should_soft_reset
        else (resolved_object_state.primary_object or resolved_object_state.active_object)
    )

    primary_route = agent_state.primary_route_decision
    contributions = [
        _build_ingestion_contribution(intent_groups),
        _build_objects_contribution(resolved_object_state, should_soft_reset),
        _build_routing_contribution(primary_route, memory_context.snapshot, final_response, _to_object_ref(active_object), should_soft_reset),
        _build_response_contribution(response_bundle.response_plan),
    ]

    updated_snapshot = reflect(
        current_snapshot=memory_context.snapshot,
        contributions=contributions,
        thread_id=thread_id,
        normalized_query=ingestion_bundle.turn_core.normalized_query or ingestion_bundle.turn_core.raw_query,
        last_turn_type=final_response.response_type,
    )
    waiting_for_user = final_response.response_type in ("clarification", "partial_answer")
    route_phase = "waiting_for_user" if waiting_for_user else "active"
    route_state = snapshot_to_route_state(
        updated_snapshot,
        route_phase=route_phase,
        last_assistant_prompt_type=final_response.response_type,
    )
    assistant_message = {
        "role": "assistant",
        "content": final_response.message or reply_preview,
        "metadata": {
            "response_type": final_response.response_type,
            "response_topic": response_bundle.response_topic,
            "response_path": response_bundle.response_path,
            "grounded_action_types": list(final_response.grounded_action_types),
            "content_blocks": list(response_content_blocks),
            "needs_human_handoff": final_response.needs_human_handoff,
            "response_debug": response_bundle.composed_response.debug_info,
            "agent_debug": agent_state.debug_summary(),
            "semantic_debug": demand_profile.model_dump(mode="json"),
            "memory_snapshot": serialize_memory_snapshot(updated_snapshot),
            "route_state": route_state,
        },
    }
    session_store.append_turns(
        thread_id,
        [
            {"role": "user", "content": user_query, "metadata": {}},
            assistant_message,
        ],
    )
    session_store.persist_memory_snapshot(
        thread_id, updated_snapshot,
        route_phase=route_phase,
        last_assistant_prompt_type=final_response.response_type,
    )
    return assistant_message


def _assemble_agent_response(
    ingestion_bundle,
    resolved_object_state,
    intent_groups: list[IntentGroup],
    demand_profile: DemandProfile,
    agent_state: AgentState,
    execution_plan_payload: dict[str, Any],
    execution_run_payload: dict[str, Any],
    response_bundle,
    response_content_blocks: list[dict[str, Any]],
    final_response: FinalResponsePayload,
    reply_preview: str,
    assistant_message: dict[str, Any],
    *,
    locale: str = "zh",
) -> AgentPrototypeResponse:
    primary_route = agent_state.primary_route_decision
    return AgentPrototypeResponse(
        parsed={
            "turn_core": ingestion_bundle.turn_core.model_dump(mode="json"),
            "parser_signals": ingestion_bundle.turn_signals.parser_signals.model_dump(mode="json"),
            "deterministic_signals": ingestion_bundle.turn_signals.deterministic_signals.model_dump(mode="json"),
            "reference_signals": ingestion_bundle.turn_signals.reference_signals.model_dump(mode="json"),
            "intent_groups": [group.model_dump(mode="json") for group in intent_groups],
            "demand_profile": demand_profile.model_dump(mode="json"),
        },
        agent_input=_build_agent_input_payload(
            ingestion_bundle,
            resolved_object_state,
            agent_state,
            demand_profile,
        ),
        route=primary_route.model_dump(mode="json"),
        suggested_workflow=_build_suggested_workflow(agent_state.overall_action, execution_plan_payload, locale=locale),
        reply_preview=reply_preview,
        execution_plan=execution_plan_payload,
        execution_run=execution_run_payload,
        answer_focus=response_bundle.response_plan.answer_focus,
        response_topic=response_bundle.response_topic,
        response_content_blocks=response_content_blocks,
        response_content_summary=response_bundle.response_content_summary,
        response_path=response_bundle.response_path,
        final_response=final_response,
        assistant_message=assistant_message,
    )


def _run_agent_loop(
    intent_groups: list[IntentGroup],
    demand_profile: DemandProfile,
    ingestion_bundle,
    resolved_object_state,
    memory_context: MemoryContext,
) -> AgentState:
    """Phase 2: iterate over intent groups, route and execute each independently.

    A shared ToolCallCache enables:
    - Deduplication: if group A already called catalog_lookup_tool for "CAR-T",
      group B reuses the cached result instead of calling again.
    - Cross-group observation: facts discovered by group A (e.g., product name,
      business_line) are passed to group B's tool requests as enriched context.

    Path evaluation (post-tool-selection) determines whether the system should
    execute or clarify.  Clarification only triggers when ALL candidate paths
    are insufficient and resolution chain cannot help.
    """
    from src.agent.tool_call_cache import ToolCallCache
    from src.executor.engine import build_execution_context, extract_available_params
    from src.executor.path_evaluation import (
        evaluate_execution_paths,
        find_resolution_provider,
    )
    from src.executor.tool_selector import select_tools
    from src.routing.models import ClarificationPayload

    agent_state = AgentState()
    cache = ToolCallCache()

    for group in intent_groups:
        # Compute scoped demand ONCE per group — shared by routing and executor
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

        if route_decision.action == "execute":
            # Build context (shared by path evaluation and executor)
            context = build_execution_context(
                ingestion_bundle=ingestion_bundle,
                resolved_object_state=resolved_object_state,
                route_decision=route_decision,
                memory_snapshot=memory_context.snapshot,
                focus_group=group,
                demand_profile=demand_profile,
                tool_call_cache=cache,
                active_demand=scoped_demand,
            )

            # Path evaluation: select tools → assess readiness → decide
            selections = select_tools(context)
            available_params = extract_available_params(context, tool_call_cache=cache)
            obj_type = context.primary_object.object_type if context.primary_object else ""

            path_eval = evaluate_execution_paths(selections, obj_type, available_params)

            if path_eval.recommended_action == "execute":
                # Normal execution — run_executor handles dispatch + retry loop
                execution_result = run_executor(
                    ingestion_bundle=ingestion_bundle,
                    resolved_object_state=resolved_object_state,
                    route_decision=route_decision,
                    memory_snapshot=memory_context.snapshot,
                    focus_group=group,
                    demand_profile=demand_profile,
                    tool_call_cache=cache,
                    active_demand=scoped_demand,
                )
                status = (
                    "resolved"
                    if execution_result.final_status in ("ok", "partial")
                    else "needs_clarification"
                )
            else:
                # All paths insufficient — try resolution chain
                provider = find_resolution_provider(path_eval, available_params)
                if provider is not None:
                    # Run executor with resolution provider as force_include
                    execution_result = run_executor(
                        ingestion_bundle=ingestion_bundle,
                        resolved_object_state=resolved_object_state,
                        route_decision=route_decision,
                        memory_snapshot=memory_context.snapshot,
                        focus_group=group,
                        demand_profile=demand_profile,
                        tool_call_cache=cache,
                        active_demand=scoped_demand,
                    )
                    status = (
                        "resolved"
                        if execution_result.final_status in ("ok", "partial")
                        else "needs_clarification"
                    )
                else:
                    # Truly blocked — override to clarify
                    execution_result = empty_execution_result(
                        reason="all execution paths insufficient",
                    )
                    if path_eval.clarification_context is not None:
                        missing_info = []
                        for ids_list in path_eval.clarification_context.missing_by_path.values():
                            for identifier in ids_list:
                                if identifier not in missing_info:
                                    missing_info.append(identifier)
                        route_decision = route_decision.model_copy(update={
                            "action": "clarify",
                            "clarification": ClarificationPayload(
                                kind="path_evaluation",
                                reason="All candidate execution paths are insufficient.",
                                missing_information=missing_info,
                                path_context=path_eval.clarification_context,
                            ),
                        })
                    else:
                        route_decision = route_decision.model_copy(update={
                            "action": "clarify",
                        })
                    status = "needs_clarification"

        elif route_decision.action == "handoff":
            execution_result = empty_execution_result(reason="needs handoff")
            status = "needs_handoff"
        elif route_decision.action == "clarify":
            execution_result = empty_execution_result(reason="needs clarification")
            status = "needs_clarification"
        else:
            execution_result = empty_execution_result(
                reason=f"No execution needed: action={route_decision.action}",
            )
            status = "resolved"

        # Post-execution RAG confidence override (per-group).
        # Phase 1: log only; override stays dark behind _RAG_CONFIDENCE_HANDOFF_ENABLED.
        if route_decision.action == "execute":
            rag_confidence = _extract_rag_confidence(execution_result)
            if rag_confidence is not None:
                logger.info(
                    "rag_confidence thread=%s confidence=%s",
                    ingestion_bundle.turn_core.thread_id,
                    rag_confidence,
                )
                if (
                    _RAG_CONFIDENCE_HANDOFF_ENABLED
                    and rag_confidence.get("level") == "low"
                ):
                    route_decision = route_decision.model_copy(update={"action": "handoff"})
                    execution_result = empty_execution_result(
                        reason=(
                            "rag confidence too low: "
                            f"top_final={rag_confidence.get('top_final_score', 0.0):.3f} "
                            f"margin={rag_confidence.get('top_margin', 0.0):.3f}"
                        ),
                    )
                    status = "needs_handoff"

        agent_state.record(
            group, route_decision, execution_result,
            status=status, scoped_demand=scoped_demand,
        )

    return agent_state


def run_email_agent(request: AgentRequest | dict[str, Any]) -> AgentPrototypeResponse:
    if isinstance(request, dict):
        request = AgentRequest.model_validate(request)

    # --- Phase 1: Understand ---
    session_store, memory_snapshot, merged_history, attachments = _load_session_context(request)

    memory_context = recall(
        thread_id=request.thread_id,
        user_query=request.user_query,
        prior_state=memory_snapshot,
    )

    ingestion_bundle = build_ingestion_bundle(
        thread_id=request.thread_id,
        user_query=request.user_query,
        conversation_history=merged_history,
        attachments=attachments,
        prior_state=memory_context.snapshot,
        stateful_anchors=memory_context.stateful_anchors,
        has_recent_objects=bool(memory_context.recent_objects_by_relevance),
    )
    resolved_object_state = resolve_objects(
        ingestion_bundle,
        trajectory_phase=memory_context.trajectory.phase,
        recent_objects=memory_context.recent_objects_by_relevance,
    )
    intent_groups = assemble_intent_groups(
        request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
        resolved_objects=[
            resolved_object_state.primary_object,
            *resolved_object_state.secondary_objects,
        ],
        semantic_intent=ingestion_bundle.turn_signals.parser_signals.context.semantic_intent,
    )
    demand_profile = build_demand_profile(
        ingestion_bundle.turn_signals.parser_signals,
        intent_groups,
        prior_demand_type=memory_context.prior_demand_type,
        prior_demand_flags=memory_context.prior_demand_flags,
        continuity_confidence=memory_context.intent_continuity_confidence,
    )
    query = ingestion_bundle.turn_core.normalized_query or request.user_query

    # --- Phase 2: Agent loop — route and execute each intent group ---
    agent_state = _run_agent_loop(
        intent_groups, demand_profile, ingestion_bundle, resolved_object_state, memory_context,
    )

    # --- Phase 3: Respond — merge all group outcomes into one response ---
    execution_result = agent_state.merged_execution_result

    parser_signals = ingestion_bundle.turn_signals.parser_signals
    response_bundle = build_response_bundle(ResponseInput(
        query=query,
        locale=request.locale,
        execution_result=execution_result,
        resolved_object_state=resolved_object_state,
        dialogue_act=agent_state.primary_dialogue_act,
        response_memory=memory_context.snapshot.response_memory,
        action=agent_state.overall_action,
        clarification=agent_state.primary_clarification,
        group_outcomes=list(agent_state.outcomes),
        demand_profile=demand_profile,
        parser_constraints=parser_signals.constraints,
        parser_open_slots=parser_signals.open_slots,
    ))

    # --- Phase 4: Serialize ---
    execution_plan_payload = _serialize_execution_plan(execution_result)
    execution_run_payload = _serialize_execution_run(execution_result)
    response_content_blocks = _serialize_content_blocks(response_bundle.composed_response.content_blocks)
    final_response = _build_final_response_payload(agent_state, execution_result, response_bundle)
    reply_preview = _build_reply_preview(
        query, agent_state.overall_action, execution_run_payload, final_response,
        locale=request.locale,
    )

    # --- Phase 5: Reflect + persist ---
    assistant_message = _persist_session_state(
        session_store, request.thread_id, request.user_query,
        memory_context, ingestion_bundle, resolved_object_state,
        intent_groups, demand_profile, agent_state,
        final_response, response_bundle,
        reply_preview, response_content_blocks,
    )

    # --- Phase 6: Assemble HTTP response ---
    return _assemble_agent_response(
        ingestion_bundle, resolved_object_state, intent_groups, demand_profile, agent_state,
        execution_plan_payload, execution_run_payload,
        response_bundle, response_content_blocks,
        final_response, reply_preview, assistant_message,
        locale=request.locale,
    )
