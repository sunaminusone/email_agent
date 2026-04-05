from __future__ import annotations

import re

from src.schemas import FinalResponse


def postprocess_generated_response(bundle: dict) -> FinalResponse:
    payload = bundle["payload"]
    response = bundle["response"]

    if not isinstance(response, FinalResponse):
        response = FinalResponse(message=str(response or "").strip())

    response.message = re.sub(r"\s+", " ", response.message or "").strip()
    if not response.message:
        response.message = payload["content_summary"] or payload["query"] or "I processed the request."

    if not response.grounded_action_types:
        if payload.get("deterministic_response") is not None:
            response.grounded_action_types = payload["deterministic_response"].grounded_action_types
        else:
            response.grounded_action_types = payload.get("action_types", [])

    if payload["topic_type"] == "clarification":
        response.response_type = "clarification"
        if not response.missing_information_requested:
            response.missing_information_requested = payload.get("missing_information", [])[:3]
    elif payload["topic_type"] == "handoff":
        response.response_type = "handoff"
        response.needs_human_handoff = True

    return response
