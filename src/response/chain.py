from __future__ import annotations

from langchain_core.runnables import RunnableLambda

from src.config import get_llm
from src.responders.renderers import RendererUnavailableError, render_topic_response
from src.schemas import FinalResponse

from .content import build_response_content
from .postprocess import postprocess_generated_response
from .preprocess import preprocess_response_data
from .prompt import get_response_prompt


def _run_topic_chain(payload: dict) -> dict:
    deterministic_response = payload.get("deterministic_response")
    if deterministic_response is not None:
        return {
            "payload": payload,
            "response": deterministic_response,
            "response_path": "deterministic",
            "legacy_fallback_used": False,
            "legacy_fallback_route": "",
            "legacy_fallback_responder": "",
            "legacy_fallback_reason": "",
        }

    try:
        rendered = render_topic_response(payload)
        return {
            "payload": payload,
            "response": rendered,
            "response_path": "renderer",
            "legacy_fallback_used": False,
            "legacy_fallback_route": "",
            "legacy_fallback_responder": "",
            "legacy_fallback_reason": payload.get("legacy_fallback_reason", ""),
        }
    except RendererUnavailableError:
        legacy_response = payload.get("legacy_fallback_response")
        if legacy_response is not None:
            return {
                "payload": payload,
                "response": legacy_response,
                "response_path": "legacy_fallback",
                "legacy_fallback_used": True,
                "legacy_fallback_route": payload.get("legacy_fallback_route", ""),
                "legacy_fallback_responder": payload.get("legacy_fallback_responder", ""),
                "legacy_fallback_reason": payload.get("legacy_fallback_reason", ""),
            }

    prompt = get_response_prompt(payload["topic_type"])
    llm = get_llm().with_structured_output(FinalResponse)
    response = (prompt | llm).invoke(
        {
            **payload["response_sections"],
            "topic_type": payload["topic_type"],
            "response_resolution_json": payload["response_resolution_json"],
            "content_blocks_section": payload["content_blocks_section"],
            "content_summary": payload["content_summary"],
        }
    )
    return {
        "payload": payload,
        "response": response,
        "response_path": "llm",
        "legacy_fallback_used": False,
        "legacy_fallback_route": "",
        "legacy_fallback_responder": "",
        "legacy_fallback_reason": payload.get("legacy_fallback_reason", ""),
    }


def build_response_chain():
    return (
        RunnableLambda(preprocess_response_data)
        | RunnableLambda(build_response_content)
        | RunnableLambda(_run_topic_chain)
        | RunnableLambda(postprocess_generated_response)
    )


def run_response_pipeline(payload: dict) -> dict:
    preprocessed = preprocess_response_data(payload)
    content_payload = build_response_content(preprocessed)
    chain_output = _run_topic_chain(content_payload)
    final_response = postprocess_generated_response(chain_output)
    return {
        "final_response": final_response,
        "response_resolution": payload["response_resolution"],
        "topic_type": content_payload["topic_type"],
        "content_blocks": content_payload["content_blocks"],
        "content_summary": content_payload["content_summary"],
        "response_path": chain_output["response_path"],
        "legacy_fallback_used": chain_output["legacy_fallback_used"],
        "legacy_fallback_route": chain_output["legacy_fallback_route"],
        "legacy_fallback_responder": chain_output["legacy_fallback_responder"],
        "legacy_fallback_reason": chain_output["legacy_fallback_reason"],
    }
