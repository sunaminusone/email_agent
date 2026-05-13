from __future__ import annotations

from typing import Any

_MESSAGES: dict[str, dict[str, str]] = {
    # --- pipeline / workflow labels (v4 CSR mode: only the unified "done" /
    # execute / draft path is reachable; clarify/handoff/respond keys were
    # dropped along with the pre-pivot routing branches that referenced them) ---
    "reply_preview_done": {
        "zh": "已围绕\u201c{query}\u201d完成初步检索，本轮共执行 {action_count} 个工具。",
        "en": "Completed initial retrieval for \u201c{query}\u201d, {action_count} tool(s) executed.",
    },
    "workflow_parse_input": {
        "zh": "解析用户输入",
        "en": "Parse user input",
    },
    "workflow_extract_objects": {
        "zh": "抽取对象与约束",
        "en": "Extract objects and constraints",
    },
    "workflow_route": {
        "zh": "执行路由决策",
        "en": "Route decision",
    },
    "workflow_execute_tool": {
        "zh": "执行 {action_type}",
        "en": "Execute {action_type}",
    },
    "workflow_draft_reply": {
        "zh": "生成邮件回复草稿",
        "en": "Draft email reply",
    },
    # --- renderer: termination ---
    "response_termination": {
        "zh": "好的，本话题到此为止。",
        "en": "Understood. I will stop here on this topic.",
    },
    # --- renderer: clarification ---
    "response_clarification_default": {
        "zh": "在继续之前，我需要补充一些信息。",
        "en": "I need a bit more information before I can continue.",
    },
    # --- renderer: handoff ---
    "response_handoff": {
        "zh": "此请求需要人工复核后才能准备最终回复。",
        "en": "This request needs human review before a final email reply is prepared.",
    },
    "response_handoff_reason": {
        "zh": "{base} 原因：{reason}",
        "en": "{base} Reason: {reason}",
    },
    # --- renderer: acknowledgement ---
    "response_acknowledgement": {
        "zh": "收到。",
        "en": "Understood.",
    },
    "response_acknowledgement_noted": {
        "zh": "收到。已记录：{query}",
        "en": "Understood. I noted: {query}",
    },
    # --- renderer: answer ---
    "response_answer_no_result": {
        "zh": "已分析关于“{query}”的请求，但未能返回有依据的结果。",
        "en": "I analyzed the request about '{query}', but there was no grounded result to return.",
    },
    "response_answer_grounded": {
        "zh": "已找到关于 {object_body} 的信息。",
        "en": "I found grounded information for {object_body}.",
    },
    "response_answer_lookup_done": {
        "zh": "已完成关于“{query}”的检索。",
        "en": "I completed the requested lookup for '{query}'.",
    },
    "response_answer_resolved_object": {
        "zh": "已解析对象：{object_body}。",
        "en": "Resolved object: {object_body}.",
    },
    "response_answer_top_matches": {
        "zh": "最佳匹配：{labels}。",
        "en": "Top matches: {labels}.",
    },
    "response_answer_matched_docs": {
        "zh": "匹配到的文档：{body}。",
        "en": "Matched documents: {body}.",
    },
    "response_answer_related_records": {
        "zh": "相关记录：{body}。",
        "en": "Related records: {body}.",
    },
    # --- renderer: partial_answer ---
    "response_partial_answer": {
        "zh": "以下是目前可以回答的部分：",
        "en": "Here is what I can answer so far:",
    },
    "response_partial_clarification": {
        "zh": "另外，关于\u201c{intent}\u201d还需要补充信息：{prompt}",
        "en": "Additionally, regarding '{intent}' I need more information: {prompt}",
    },
    # --- blocks: content block titles ---
    "block_title_handoff": {
        "zh": "需要人工复核",
        "en": "Human review required",
    },
    "block_body_handoff": {
        "zh": "此请求需要人工复核后才能发送最终回复。",
        "en": "This request needs human review before a final reply can be sent.",
    },
    "block_title_resolved_object": {
        "zh": "已解析对象",
        "en": "Resolved object",
    },
    "block_title_clarification": {
        "zh": "需要补充信息",
        "en": "Clarification needed",
    },
    "block_body_clarification_default": {
        "zh": "在继续之前，我需要补充一些信息。",
        "en": "I need a bit more information before I can continue.",
    },
    # --- renderer: knowledge ---
    "response_knowledge_fallback": {
        "zh": "未能找到关于“{query}”的具体信息。请您提供更多细节，例如产品名称、货号或订单号。",
        "en": "I wasn't able to find specific information for '{query}'. Could you provide more details such as a product name, catalog number, or order number?",
    },
}


def get_message(key: str, locale: str = "zh", **kwargs: Any) -> str:
    """Look up a message by key and locale, then format with kwargs."""
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    template = entry.get(locale) or entry.get("zh", key)
    return template.format(**kwargs) if kwargs else template
