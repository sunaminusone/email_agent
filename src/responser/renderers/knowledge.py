from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from src.common.messages import get_message
from src.config import get_llm
from src.responser.models import ComposedResponse, ContentBlock, ResponseInput, ResponsePlan


class KnowledgeAnswerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""


_KNOWLEDGE_SYSTEM_PROMPTS: dict[str, str] = {
    "zh": """\
你是一名生物科技客户支持助手。

客户提出了一个通用问题，没有引用我们系统中的具体产品、订单或文档。请根据你的领域知识提供有用的回答。

规则：
1. 回复简洁、专业。
2. 不要编造产品名称、货号、价格或订单详情。
3. 如果不确定，请诚实告知，并建议客户提供更多细节。
4. 使用中文回答。""",
    "en": """\
You are a biotech customer support assistant.

The customer asked a general question that does not reference a specific product, \
order, or document in our system.  Answer helpfully using your domain knowledge.

Rules:
1. Be concise and professional.
2. Do not fabricate product names, catalog numbers, prices, or order details.
3. If you are unsure, say so honestly and suggest the customer provide more details.
4. Answer in English.""",
}


def render_knowledge_response(
    response_input: ResponseInput,
    response_plan: ResponsePlan,
) -> ComposedResponse:
    locale = response_input.locale
    try:
        message = _generate_knowledge_answer(response_input.query, locale)
    except Exception as exc:
        message = get_message("response_knowledge_fallback", locale, query=response_input.query)
        return ComposedResponse(
            message=message,
            response_type="knowledge_answer",
            content_blocks=[],
            debug_info={
                "response_mode": response_plan.response_mode,
                "reason": response_plan.reason,
                "llm_error": str(exc),
            },
        )

    content_block = ContentBlock(
        block_type="knowledge_answer",
        title="Knowledge-based answer",
        body=message,
    )

    return ComposedResponse(
        message=message,
        response_type="knowledge_answer",
        content_blocks=[content_block],
        debug_info={
            "response_mode": response_plan.response_mode,
            "reason": response_plan.reason,
        },
    )


def _generate_knowledge_answer(query: str, locale: str = "zh") -> str:
    system_prompt = _KNOWLEDGE_SYSTEM_PROMPTS.get(locale, _KNOWLEDGE_SYSTEM_PROMPTS["zh"])
    llm = get_llm().with_structured_output(KnowledgeAnswerOutput)
    messages = [
        ("system", system_prompt),
        ("human", query),
    ]
    result = llm.invoke(messages)
    return str(result.message or "").strip()
