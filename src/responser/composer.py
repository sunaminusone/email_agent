from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from src.config import get_llm
from src.responser.models import ComposedResponse, ResponsePlan
from src.responser.prompts import get_rewrite_prompt


class RewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""


def compose_final_response(
    draft: ComposedResponse,
    response_plan: ResponsePlan,
    *,
    locale: str = "zh",
) -> ComposedResponse:
    if not response_plan.should_use_llm_rewrite:
        draft.debug_info.setdefault("response_path", "deterministic")
        return draft

    try:
        rewritten_message = _rewrite_message(draft, response_plan, locale=locale)
    except Exception as exc:
        draft.debug_info.update(
            {
                "response_path": "deterministic",
                "rewrite_applied": False,
                "rewrite_error": str(exc),
            }
        )
        return draft

    rewritten = draft.model_copy(deep=True)
    rewritten.message = rewritten_message or draft.message
    rewritten.debug_info.update(
        {
            "response_path": "llm_rewrite",
            "rewrite_applied": True,
        }
    )
    return rewritten


def _rewrite_message(
    draft: ComposedResponse,
    response_plan: ResponsePlan,
    *,
    locale: str = "zh",
) -> str:
    llm = get_llm().with_structured_output(RewriteOutput)
    prompt = get_rewrite_prompt(locale)
    content_blocks_json = json.dumps(
        [block.model_dump(mode="json") for block in draft.content_blocks],
        ensure_ascii=False,
        indent=2,
    )
    rewritten = (prompt | llm).invoke(
        {
            "response_mode": response_plan.response_mode,
            "draft_message": draft.message,
            "content_blocks_json": content_blocks_json,
        }
    )
    return str(rewritten.message or "").strip()
