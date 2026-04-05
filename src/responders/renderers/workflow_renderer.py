from __future__ import annotations

from src.responders.render_helpers import join_sentences
from src.schemas import FinalResponse

from .common import InsufficientContentError, answer


def render_workflow(payload: dict) -> FinalResponse:
    language = payload["language"]
    resolution = payload["response_resolution"]
    blocks = {block.kind: block for block in payload["content_blocks"]}
    workflow_block = blocks.get("workflow_status")

    if not workflow_block:
        raise InsufficientContentError("Workflow renderer requires a workflow_status block.")

    business_line = workflow_block.payload.get("business_line") or "unknown"
    missing_information = workflow_block.payload.get("missing_information") or []

    if language == "zh":
        if missing_information:
            message = (
                f"我已经进入 workflow intake 阶段，当前识别为 {business_line} 相关定制需求。"
                f"接下来还需要这些信息：{'；'.join(missing_information[:4])}。"
            )
            return FinalResponse(
                message=message,
                response_type="clarification",
                missing_information_requested=missing_information[:4],
                grounded_action_types=[resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"],
            )
        message = f"我已经进入 workflow intake 阶段，当前识别为 {business_line} 相关定制需求，接下来可以继续整理项目范围和规格。"
        return answer(message, [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])

    if missing_information:
        message = (
            f"I entered the workflow intake stage for a {business_line} customization request. "
            f"I still need these details: {'; '.join(missing_information[:4])}."
        )
        return FinalResponse(
            message=join_sentences([message]),
            response_type="clarification",
            missing_information_requested=missing_information[:4],
            grounded_action_types=[resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"],
        )

    message = f"I entered the workflow intake stage for a {business_line} customization request and can continue organizing the project scope and specifications."
    return answer(join_sentences([message]), [resolution.primary_action_type] if resolution.primary_action_type else payload["action_types"])
