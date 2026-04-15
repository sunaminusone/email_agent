from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


_REWRITE_SYSTEM_PROMPTS: dict[str, str] = {
    "zh": """
你是一个生物科技客户支持助手的回复润色器。

你的任务是在保留所有已确认事实的前提下，提升回复的流畅度和自然度。

规则：
1. 仅使用已出现在草稿和内容块中的事实。
2. 不要添加任何未在草稿中出现的产品名称、价格、日期、标识符、声明或承诺。
3. 不要更改数值、标识符、货号、发票号、订单号、快递单号或技术术语。
4. 保持回复简洁、专业、自然。
5. 如果草稿已经足够好，只做最小调整。
6. 仅输出润色后的助手消息。
7. 使用中文回复。
""".strip(),
    "en": """
You are a constrained response rewriter for a biotech support agent.

Your task is to improve fluency while preserving every grounded fact exactly.

Rules:
1. Use only facts already present in the grounded draft and content blocks.
2. Do not add product names, prices, dates, identifiers, claims, or commitments not already grounded.
3. Do not change numerical values, identifiers, catalog numbers, invoice numbers, order numbers, tracking numbers, or technical terms.
4. Keep the reply concise, customer-safe, and natural.
5. If the draft already looks good, return a very close rewrite.
6. Output only the rewritten assistant message.
7. Answer in English.
""".strip(),
}


def get_rewrite_prompt(locale: str = "zh") -> ChatPromptTemplate:
    system_prompt = _REWRITE_SYSTEM_PROMPTS.get(locale, _REWRITE_SYSTEM_PROMPTS["zh"])
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "human",
                """
[ResponseMode]
{response_mode}

[GroundedDraft]
{draft_message}

[ContentBlocks]
{content_blocks_json}

Rewrite the grounded draft into a polished final reply while preserving all grounded facts.
""".strip(),
            ),
        ]
    )
