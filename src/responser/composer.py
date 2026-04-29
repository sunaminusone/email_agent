from __future__ import annotations

from src.responser.models import ComposedResponse, ResponsePlan


def compose_final_response(
    draft: ComposedResponse,
    response_plan: ResponsePlan,
    *,
    locale: str = "zh",
) -> ComposedResponse:
    # CSR mode: the renderer already produces the final structured output
    # (draft + reference cards + routing notes). No post-render rewrite —
    # running one would collapse the Slack-style sections back into prose.
    draft.debug_info.setdefault("response_path", "csr_renderer_direct")
    return draft
