from __future__ import annotations

import json

from src.schemas import FinalResponse
from .blocks import build_content_blocks
from .clarification import build_deterministic_response, clean_missing_information
from .fallback import effective_route_name, resolve_legacy_fallback, route_for_response
from src.schemas import ResponseTopic


def build_response_content(payload: dict) -> dict:
    runtime_context = payload["runtime_context"]
    agent_input = payload["agent_input"]
    route = payload["route"]
    execution_run = payload["execution_run"]
    response_resolution: ResponseResolution = payload["response_resolution"]
    action_types = payload["action_types"]
    language = payload["language"]
    query = payload["query"]

    agent_input_data = agent_input.model_dump(mode="json")
    resolved_route_name = effective_route_name(route, execution_run)
    effective_route = route.model_copy(update={"route_name": resolved_route_name})
    focused_route = route_for_response(effective_route, response_resolution.preferred_route_name)
    missing_information = clean_missing_information(
        focused_route,
        query,
        agent_input_data,
        route.missing_information_to_request or agent_input.missing_information,
    )

    deterministic_info = build_deterministic_response(
        route=route,
        effective_route_name=resolved_route_name,
        missing_information=missing_information,
        action_types=action_types,
        language=language,
        response_topic=response_resolution.topic_type,
    )
    effective_topic = deterministic_info["effective_topic"]
    deterministic_response = deterministic_info["deterministic_response"]

    legacy_fallback_result = {
        "response": None,
        "route_name": "",
        "responder_name": "",
        "reason": "",
    }
    if deterministic_response is None:
        legacy_fallback_result = resolve_legacy_fallback(
            agent_input=agent_input,
            route=route,
            focused_route=focused_route,
            execution_run=execution_run,
            response_resolution=response_resolution,
            action_types=action_types,
        )

    content_blocks = build_content_blocks(payload)
    content_summary = " ".join(block.text for block in content_blocks[:8])

    if deterministic_response is None and response_resolution.answer_focus == "acknowledgement":
        message = (
            "好的，已收到。如果你想继续，我可以继续补充这款产品的应用、反应性、价格或文档信息。"
            if language == "zh"
            else "Got it. If you'd like, I can still help with applications, reactivity, pricing, or documents for this product."
        )
        deterministic_response = FinalResponse(
            message=message,
            response_type="acknowledgement",
            grounded_action_types=action_types,
        )

    if deterministic_response is None and response_resolution.answer_focus == "conversation_close":
        message = (
            "好的，我先停在这里。后面如果你想继续这个产品或换个新问题，我们都可以接着来。"
            if language == "zh"
            else "Understood. I'll stop here for now. If you want to return to this product or start a new question later, we can pick it up then."
        )
        deterministic_response = FinalResponse(
            message=message,
            response_type="conversation_close",
            grounded_action_types=action_types,
        )

    if deterministic_response is None and response_resolution.answer_focus == "product_elaboration":
        newly_revealed = {
            block.kind
            for block in content_blocks
            if block.kind in {"target_antigen", "application", "species_reactivity", "technical_context", "documents", "price", "lead_time"}
        }
        if not newly_revealed:
            message = (
                "我已经把当前能直接确认的核心产品信息都说完了。如果你愿意，我可以继续帮你看价格、交期、文档，或者你也可以指定想看的属性。"
                if language == "zh"
                else "I've already shared the main grounded product details I can confirm right now. If you'd like, I can keep going with pricing, lead time, documents, or a specific attribute you care about."
            )
            deterministic_response = FinalResponse(
                message=message,
                response_type="answer",
                grounded_action_types=action_types,
            )

    return {
        **payload,
        "effective_route": effective_route,
        "focused_route": focused_route,
        "missing_information": missing_information,
        "topic_type": effective_topic.value if isinstance(effective_topic, ResponseTopic) else str(effective_topic),
        "deterministic_response": deterministic_response,
        "legacy_fallback_response": legacy_fallback_result["response"],
        "legacy_fallback_route": legacy_fallback_result["route_name"],
        "legacy_fallback_responder": legacy_fallback_result["responder_name"],
        "legacy_fallback_reason": legacy_fallback_result["reason"],
        "content_blocks": content_blocks,
        "content_blocks_section": json.dumps(
            [block.model_dump(mode="json") for block in content_blocks],
            ensure_ascii=False,
            indent=2,
        ),
        "content_summary": content_summary,
        "response_resolution_json": response_resolution.model_dump_json(indent=2),
        "runtime_context": runtime_context,
    }
