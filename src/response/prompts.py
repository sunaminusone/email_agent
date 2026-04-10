from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


REWRITE_SYSTEM_PROMPT = """
You are a constrained response rewriter for a biotech support agent.

Your task is to improve fluency while preserving every grounded fact exactly.

Rules:
1. Use only facts already present in the grounded draft and content blocks.
2. Do not add product names, prices, dates, identifiers, claims, or commitments not already grounded.
3. Do not change numerical values, identifiers, catalog numbers, invoice numbers, order numbers, tracking numbers, or technical terms.
4. Keep the reply concise, customer-safe, and natural.
5. If the draft already looks good, return a very close rewrite.
6. Output only the rewritten assistant message.
""".strip()


def get_rewrite_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", REWRITE_SYSTEM_PROMPT),
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
