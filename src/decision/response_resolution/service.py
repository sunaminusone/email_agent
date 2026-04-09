from __future__ import annotations

from src.schemas import AgentContext, ExecutionRun, ResponseResolution, RouteDecision

from .common import build_response_signal_context
from .content_policy import resolve_response_content_plan
from .dialogue_act import resolve_dialogue_act
from .focus_policy import resolve_response_focus
from .style_policy import resolve_reply_style
from .topic_policy import resolve_response_topic


def resolve_response(
    agent_input: AgentContext,
    route: RouteDecision,
    execution_run: ExecutionRun,
) -> ResponseResolution:
    signal_ctx = build_response_signal_context(agent_input, execution_run)
    dialogue_act_info = resolve_dialogue_act(agent_input, route, signal_ctx)
    signal_ctx["dialogue_act"] = dialogue_act_info["dialogue_act"]
    signal_ctx["dialogue_act_reason"] = dialogue_act_info["reason"]
    signal_ctx["dialogue_act_confidence"] = dialogue_act_info["confidence"]
    focus_info = resolve_response_focus(agent_input, route, signal_ctx)
    answer_focus = focus_info["answer_focus"]
    topic_type = resolve_response_topic(answer_focus=answer_focus, route_name=route.route_name)
    reply_style = resolve_reply_style(answer_focus=answer_focus, query=signal_ctx["query"])
    content_plan = resolve_response_content_plan(agent_input, route, signal_ctx, answer_focus)

    return ResponseResolution(
        topic_type=topic_type,
        dialogue_act=dialogue_act_info["dialogue_act"],
        answer_focus=answer_focus,
        primary_action_type=focus_info["primary_action_type"],
        supporting_action_types=focus_info["supporting_action_types"],
        preferred_route_name=focus_info["preferred_route_name"],
        reply_style=reply_style,
        content_priority=content_plan.get("content_priority", []),
        include_product_identity=content_plan.get("include_product_identity", False),
        include_price=content_plan.get("include_price", False),
        include_lead_time=content_plan.get("include_lead_time", False),
        include_documents=content_plan.get("include_documents", False),
        include_technical_context=content_plan.get("include_technical_context", False),
        include_target_antigen=content_plan.get("include_target_antigen", False),
        include_application=content_plan.get("include_application", False),
        include_species_reactivity=content_plan.get("include_species_reactivity", False),
        include_next_step_guidance=content_plan.get("include_next_step_guidance", False),
        should_use_summary_responder=content_plan.get("should_use_summary_responder", False),
        should_ask_clarification=content_plan.get("should_ask_clarification", False),
        should_suppress_generic_summary=content_plan.get("should_suppress_generic_summary", False),
        reason=focus_info["reason"],
        confidence=focus_info["confidence"],
    )
