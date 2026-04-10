# 核心调度器 Orchestrator
import json
from typing import List, Union

from src.context import ContextProvider
from src.memory import SessionStore
from src.schemas import AgentContext
from src.schemas.chat_schema import AgentPrototypeResponse, AgentRequest
from src.conversation.agent_input_service import make_agent_input
from src.decision.response_service import build_response_artifacts
from src.decision.route_decision_service import route_agent_input
from src.orchestration.executor_service import execute_plan
from src.orchestration.planner_service import build_execution_plan


def _extract_catalog_candidates_from_question(question: str) -> list[str]:
    candidates: list[str] = []
    for line in str(question or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        payload = stripped[2:].strip()
        catalog_no = payload.split("|", 1)[0].strip()
        if catalog_no:
            candidates.append(catalog_no)
    return candidates


def _revealed_attributes_from_response(response_resolution) -> list[str]:
    revealed: list[str] = []
    if response_resolution.include_product_identity:
        revealed.append("identity")
    if response_resolution.include_target_antigen:
        revealed.append("target_antigen")
    if response_resolution.include_application:
        revealed.append("application")
    if response_resolution.include_species_reactivity:
        revealed.append("species_reactivity")
    if response_resolution.include_technical_context:
        revealed.append("technical_context")
    if response_resolution.include_documents:
        revealed.append("documents")
    if response_resolution.include_price:
        revealed.append("price")
    if response_resolution.include_lead_time:
        revealed.append("lead_time")
    return revealed


def _message_signature(message: dict) -> tuple[str, str, str]:
    metadata = message.get("metadata", {}) or {}
    return (
        message.get("role", "user"),
        message.get("content", ""),
        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


def _merge_histories(
    persisted_history: list[dict],
    request_history: list[dict],
) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for message in persisted_history + request_history:
        signature = _message_signature(message)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(message)

    return merged


def _build_route_state(agent_input: AgentContext, route, final_response, response_resolution) -> dict:
    is_clarification_response = final_response.response_type in {"clarification", "clarification_request"}
    route_phase = "waiting_for_user" if is_clarification_response else "active"
    pending_route = None
    if is_clarification_response and route.route_name != "clarification_request":
        pending_route = route.route_name

    session_payload = agent_input.session_payload.model_dump(mode="json")
    pending_identifiers = list(agent_input.product_lookup_keys.ambiguous_identifiers)
    clarification_prompt = route.missing_information_to_request[0] if route.missing_information_to_request else ""

    if (
        is_clarification_response
        and route.route_name == "clarification_request"
        and clarification_prompt.startswith('I found multiple products matching "')
    ):
        candidate_options = _extract_catalog_candidates_from_question(clarification_prompt)
        session_payload["pending_clarification"] = {
            "field": "product_selection",
            "candidate_identifier": "",
            "candidate_options": candidate_options,
            "question": clarification_prompt,
        }
        pending_identifiers = candidate_options

    newly_revealed = _revealed_attributes_from_response(response_resolution)
    existing_revealed = list(session_payload.get("revealed_attributes", []) or [])
    session_payload["revealed_attributes"] = list(dict.fromkeys(existing_revealed + newly_revealed))

    if final_response.response_type == "conversation_close":
        active_entity = dict(session_payload.get("active_entity", {}) or {})
        if active_entity.get("entity_kind") == "product":
            session_payload["active_product_name"] = ""
            session_payload["revealed_attributes"] = []
            session_payload["pending_clarification"] = {
                "field": "",
                "candidate_identifier": "",
                "candidate_options": [],
                "question": "",
            }
            session_payload["active_entity"] = {
                "identifier": "",
                "identifier_type": "",
                "entity_kind": "",
                "display_name": "",
                "business_line": session_payload.get("active_business_line", ""),
            }
            pending_identifiers = []

    return {
        "active_route": route.route_name,
        "active_business_line": route.business_line,
        "active_engagement_type": route.engagement_type,
        "pending_route_after_clarification": pending_route,
        "active_secondary_routes": route.secondary_routes,
        "route_phase": route_phase,
        "last_assistant_prompt_type": final_response.response_type,
        "carried_missing_information": final_response.missing_information_requested or agent_input.missing_information,
        "pending_identifiers": pending_identifiers,
        "session_payload": session_payload,
    }


def build_reply_preview(agent_input: AgentContext) -> str:
    intent = agent_input.context.primary_intent
    missing_information = agent_input.missing_information
    query = agent_input.query

    if missing_information:
        questions = "；".join(missing_information[:3])
        return (
            f"已收到你的请求：{query}。\n"
            f"当前系统判断意图为 {intent}，但还需要补充这些信息后才能给出更稳妥的邮件草稿：{questions}。"
        )

    if intent == "pricing_question":
        return f"已识别为价格相关咨询。系统接下来可以基于 {query} 生成询价邮件或报价回复草稿。"
    if intent == "technical_question":
        return f"已识别为技术咨询。系统接下来可以结合知识库为 {query} 生成技术回复草稿。"
    if intent == "order_support":
        return f"已识别为订单支持请求。系统接下来可以围绕 {query} 检索订单状态并起草回复。"

    return f"已完成用户意图解析。系统接下来可以围绕“{query}”继续检索资料并生成邮件回复。"


def build_suggested_workflow(agent_input: AgentContext, route_name: str) -> List[str]:
    workflow = ["解析用户输入", "生成标准化 agent 输入"]
    route_to_step = {
        "clarification_request": "生成补充信息请求",
        "commercial_agent": "进入 Commercial Agent 选择产品/价格/文档/技术工具",
        "operational_agent": "进入 Operational Agent 选择客户/发票/订单/物流工具",
        "workflow_agent": "进入 Workflow Agent 处理定制化或多步录入流程",
        "pricing_lookup": "查询产品价格或交期",
        "product_lookup": "查询标准产品信息",
        "technical_rag": "检索技术知识库",
        "documentation_lookup": "检索产品文档",
        "shipping_support": "查询物流与地区限制",
        "order_support": "查询订单系统",
        "complaint_review": "转人工复核投诉内容",
        "partnership_review": "转业务负责人评估",
        "general_response": "整理通用答复要点",
        "human_review": "升级到人工审核",
    }
    workflow.append(route_to_step.get(route_name, "执行下游处理流程"))

    workflow.append("生成邮件回复草稿")
    return workflow


def run_email_agent(request: Union[AgentRequest, dict]) -> AgentPrototypeResponse:
    if isinstance(request, dict):
        request = AgentRequest.model_validate(request)

    session_store = SessionStore()
    persisted_history = session_store.get_recent_turns(request.thread_id)
    request_history = [message.model_dump() for message in request.conversation_history]
    history = _merge_histories(persisted_history, request_history)
    attachments = [attachment.model_dump() for attachment in request.attachments]

    agent_input = make_agent_input(
        user_query=request.user_query,
        thread_id=request.thread_id,
        conversation_history=history,
        attachments=attachments,
    )
    runtime_context = ContextProvider().build(agent_input)
    routed = route_agent_input(runtime_context)
    enriched_runtime_context = routed.runtime_context
    enriched_context = enriched_runtime_context.agent_context
    route = routed.route
    execution_plan = build_execution_plan(enriched_context, route)
    execution_run = execute_plan(enriched_context, execution_plan)
    response_artifacts = build_response_artifacts(enriched_runtime_context, route, execution_run)
    final_response = response_artifacts["final_response"]
    assistant_message = {
        "role": "assistant",
        "content": final_response.message,
        "metadata": {
            "response_type": final_response.response_type,
            "response_topic": response_artifacts["response_topic"],
            "response_path": response_artifacts["response_path"],
            "legacy_fallback_used": response_artifacts["legacy_fallback_used"],
            "legacy_fallback_route": response_artifacts["legacy_fallback_route"],
            "legacy_fallback_responder": response_artifacts["legacy_fallback_responder"],
            "legacy_fallback_reason": response_artifacts["legacy_fallback_reason"],
            "grounded_action_types": final_response.grounded_action_types,
            "content_blocks": [
                block.model_dump(mode="json") for block in response_artifacts["response_content_blocks"]
            ],
            "needs_human_handoff": final_response.needs_human_handoff,
            "route_state": _build_route_state(
                enriched_context,
                route,
                final_response,
                response_artifacts["response_resolution"],
            ),
        },
    }
    session_store.append_turns(
        request.thread_id,
        [
            {"role": "user", "content": request.user_query, "metadata": {}},
            assistant_message,
        ],
    )
    session_store.update_route_state(
        request.thread_id,
        assistant_message["metadata"]["route_state"],
    )

    return AgentPrototypeResponse(
        parsed=parsed,
        agent_input=enriched_context,
        route=route,
        suggested_workflow=build_suggested_workflow(enriched_context, route.route_name),
        reply_preview=final_response.message or build_reply_preview(enriched_context),
        execution_plan=execution_plan,
        execution_run=execution_run,
        response_resolution=response_artifacts["response_resolution"],
        response_topic=response_artifacts["response_topic"],
        response_content_blocks=response_artifacts["response_content_blocks"],
        response_content_summary=response_artifacts["response_content_summary"],
        response_path=response_artifacts["response_path"],
        legacy_fallback_used=response_artifacts["legacy_fallback_used"],
        legacy_fallback_route=response_artifacts["legacy_fallback_route"],
        legacy_fallback_responder=response_artifacts["legacy_fallback_responder"],
        legacy_fallback_reason=response_artifacts["legacy_fallback_reason"],
        final_response=final_response,
        assistant_message=assistant_message,
    )
