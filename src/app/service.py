from __future__ import annotations

import json
from typing import Any

from src.api_models import AgentPrototypeResponse, AgentRequest, FinalResponsePayload
from src.execution.runtime import build_execution_plan, run_execution_plan
from src.ingestion.pipeline import build_ingestion_bundle
from src.memory import SessionStore
from src.memory.models import ResponseMemory
from src.objects.resolution import resolve_objects
from src.response import ResponseInput, build_response_bundle
from src.routing.runtime import route_from_ingestion_bundle


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


def _compat_execution_plan(plan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json")
    payload["planned_actions"] = [
        {
            "action_id": call.call_id,
            "action_type": _tool_action_type(call.tool_name),
            "tool_name": call.tool_name,
            "role": call.role,
            "priority": call.priority,
            "depends_on": list(call.depends_on),
            "can_run_in_parallel": call.can_run_in_parallel,
        }
        for call in plan.planned_calls
    ]
    return payload


def _compat_execution_run(run) -> dict[str, Any]:
    payload = run.model_dump(mode="json")
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
        for call in run.executed_calls
    ]
    payload["overall_status"] = run.final_status
    return payload


def _serialize_content_blocks(content_blocks) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for block in content_blocks:
        payload = block.model_dump(mode="json")
        payload.setdefault("kind", payload.get("block_type", ""))
        payload.setdefault("text", payload.get("body", ""))
        serialized.append(payload)
    return serialized


def _build_reply_preview(query: str, route, execution_run_payload: dict[str, Any], final_response: FinalResponsePayload) -> str:
    if final_response.message:
        return final_response.message
    if route.route_name == "clarification":
        return f"已收到你的请求：{query}。当前仍需要补充信息后才能继续。"
    if route.route_name == "handoff":
        return f"已收到你的请求：{query}。当前需要人工复核。"
    action_count = len(execution_run_payload.get("executed_actions", []))
    return f"已围绕“{query}”完成初步检索，本轮共执行 {action_count} 个工具。"


def _build_route_state(
    ingestion_bundle,
    resolved_object_state,
    route,
    final_response: FinalResponsePayload,
    response_plan=None,
) -> dict[str, Any]:
    should_soft_reset = bool(
        response_plan is not None
        and response_plan.memory_update is not None
        and response_plan.memory_update.soft_reset_current_topic
    )
    active_object = None if should_soft_reset else (resolved_object_state.primary_object or resolved_object_state.active_object)
    clarification = route.clarification
    route_state = {
        "active_route": route.route_name,
        "route_phase": "waiting_for_user" if final_response.response_type == "clarification" else "active",
        "last_assistant_prompt_type": final_response.response_type,
        "thread_memory": {
            "active_route": route.route_name,
            "active_business_line": getattr(active_object, "business_line", "") if active_object is not None else "",
        },
        "object_memory": {
            "active_object": (
                {
                    "object_type": active_object.object_type,
                    "identifier": active_object.identifier,
                    "display_name": active_object.display_name or active_object.canonical_value,
                    "business_line": active_object.business_line,
                }
                if active_object is not None
                else {}
            ),
        },
        "clarification_memory": {
            "pending_clarification_type": "" if should_soft_reset else (clarification.kind if clarification is not None else ""),
            "pending_candidate_options": [] if should_soft_reset else [option.label or option.value for option in (clarification.options if clarification is not None else [])],
            "pending_identifier": "",
        },
        "response_memory": (
            response_plan.memory_update.response_memory.model_dump(mode="json")
            if response_plan is not None and response_plan.memory_update is not None and response_plan.memory_update.response_memory is not None
            else {}
        ),
        "session_payload": {
            "thread_id": ingestion_bundle.turn_core.thread_id,
            "active_query": ingestion_bundle.turn_core.normalized_query,
        },
    }
    return route_state


def _build_agent_input_payload(ingestion_bundle, resolved_object_state, route) -> dict[str, Any]:
    parser_context = ingestion_bundle.turn_signals.parser_signals.context
    intent = route.execution_intent
    return {
        "thread_id": ingestion_bundle.turn_core.thread_id,
        "query": ingestion_bundle.turn_core.normalized_query,
        "raw_query": ingestion_bundle.turn_core.raw_query,
        "primary_intent": parser_context.primary_intent,
        "missing_information": (
            list(route.clarification.missing_information)
            if route.clarification is not None
            else list(ingestion_bundle.turn_signals.parser_signals.missing_information)
        ),
        "resolved_object_state": resolved_object_state.model_dump(mode="json"),
        "routing_debug": {
            "route_name": route.route_name,
            "active_route": route.route_name,
            "intent": parser_context.primary_intent,
            "intent_confidence": parser_context.intent_confidence,
            "business_line": getattr(intent.primary_object, "business_line", "") if intent.primary_object is not None else "",
            "business_line_confidence": resolved_object_state.resolution_confidence,
            "engagement_type": intent.dialogue_act.act,
            "selected_tools": list(intent.selected_tools),
            "needs_clarification": intent.needs_clarification,
            "handoff_required": intent.handoff_required,
        },
    }


def _build_suggested_workflow(route, execution_plan_payload: dict[str, Any]) -> list[str]:
    workflow = [
        "解析用户输入",
        "抽取对象与约束",
        "执行路由决策",
    ]
    if route.route_name == "clarification":
        workflow.append("生成补充信息请求")
        return workflow
    if route.route_name == "handoff":
        workflow.append("升级到人工复核")
        return workflow

    planned_actions = execution_plan_payload.get("planned_actions", [])
    if planned_actions:
        workflow.extend([f"执行 {action['action_type']}" for action in planned_actions])
    workflow.append("生成邮件回复草稿")
    return workflow


def run_email_agent(request: AgentRequest | dict[str, Any]) -> AgentPrototypeResponse:
    if isinstance(request, dict):
        request = AgentRequest.model_validate(request)

    session_store = SessionStore()
    session = session_store.load_session(request.thread_id)
    persisted_history = session.get("recent_turns", [])
    request_history = [message.model_dump(mode="json") for message in request.conversation_history]
    merged_history = _merge_histories(persisted_history, request_history)
    attachments = [attachment.model_dump(mode="json") for attachment in request.attachments]

    ingestion_bundle = build_ingestion_bundle(
        thread_id=request.thread_id,
        user_query=request.user_query,
        conversation_history=merged_history,
        attachments=attachments,
        prior_state=session.get("route_state"),
    )
    resolved_object_state = resolve_objects(ingestion_bundle)
    route = route_from_ingestion_bundle(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved_object_state,
    )
    execution_plan = build_execution_plan(route.execution_intent)
    execution_run = run_execution_plan(execution_plan)
    stored_response_memory = ResponseMemory.model_validate(
        (session.get("route_state", {}) or {}).get("response_memory", {}) or {}
    )

    response_input = ResponseInput(
        query=ingestion_bundle.turn_core.normalized_query or request.user_query,
        execution_run=execution_run,
        resolved_object_state=resolved_object_state,
        dialogue_act=route.execution_intent.dialogue_act,
        response_memory=stored_response_memory,
        route_name=route.route_name,
        clarification=route.clarification,
    )
    response_bundle = build_response_bundle(response_input)

    execution_plan_payload = _compat_execution_plan(execution_plan)
    execution_run_payload = _compat_execution_run(execution_run)
    response_content_blocks = _serialize_content_blocks(response_bundle.composed_response.content_blocks)
    response_resolution = response_bundle.response_resolution.model_dump(mode="json")
    response_topic = response_bundle.response_topic
    response_content_summary = response_bundle.response_content_summary
    final_response = FinalResponsePayload(
        message=response_bundle.composed_response.message,
        response_type=response_bundle.composed_response.response_type,
        grounded_action_types=[
            _tool_action_type(call.tool_name)
            for call in execution_run.executed_calls
            if call.status != "error"
        ],
        needs_human_handoff=response_bundle.composed_response.response_type == "handoff",
        missing_information_requested=(
            list(route.clarification.missing_information)
            if route.clarification is not None
            else []
        ),
    )
    reply_preview = _build_reply_preview(
        ingestion_bundle.turn_core.normalized_query or request.user_query,
        route,
        execution_run_payload,
        final_response,
    )
    route_state = _build_route_state(
        ingestion_bundle,
        resolved_object_state,
        route,
        final_response,
        response_bundle.response_plan,
    )
    assistant_message = {
        "role": "assistant",
        "content": final_response.message or reply_preview,
        "metadata": {
            "response_type": final_response.response_type,
            "response_topic": response_topic,
            "response_path": response_bundle.response_path,
            "legacy_fallback_used": False,
            "legacy_fallback_route": "",
            "legacy_fallback_responder": "",
            "legacy_fallback_reason": "",
            "grounded_action_types": list(final_response.grounded_action_types),
            "content_blocks": list(response_content_blocks),
            "needs_human_handoff": final_response.needs_human_handoff,
            "response_debug": response_bundle.composed_response.debug_info,
            "route_state": route_state,
        },
    }

    session_store.append_turns(
        request.thread_id,
        [
            {"role": "user", "content": request.user_query, "metadata": {}},
            assistant_message,
        ],
    )
    session_store.update_route_state(request.thread_id, route_state)

    return AgentPrototypeResponse(
        parsed={
            "turn_core": ingestion_bundle.turn_core.model_dump(mode="json"),
            "parser_signals": ingestion_bundle.turn_signals.parser_signals.model_dump(mode="json"),
            "deterministic_signals": ingestion_bundle.turn_signals.deterministic_signals.model_dump(mode="json"),
            "reference_signals": ingestion_bundle.turn_signals.reference_signals.model_dump(mode="json"),
        },
        agent_input=_build_agent_input_payload(ingestion_bundle, resolved_object_state, route),
        route=route.model_dump(mode="json"),
        suggested_workflow=_build_suggested_workflow(route, execution_plan_payload),
        reply_preview=reply_preview,
        execution_plan=execution_plan_payload,
        execution_run=execution_run_payload,
        response_resolution=response_resolution,
        response_topic=response_topic,
        response_content_blocks=response_content_blocks,
        response_content_summary=response_content_summary,
        response_path=response_bundle.response_path,
        legacy_fallback_used=False,
        legacy_fallback_route="",
        legacy_fallback_responder="",
        legacy_fallback_reason="",
        final_response=final_response,
        assistant_message=assistant_message,
    )
