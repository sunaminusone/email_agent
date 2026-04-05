from __future__ import annotations

import json

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
