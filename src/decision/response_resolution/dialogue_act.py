from __future__ import annotations

import re
from typing import Iterable


ACK_TERMS = {
    "ok",
    "okay",
    "got it",
    "i see",
    "understood",
    "sounds good",
    "thanks",
    "thank you",
    "知道了",
    "好的",
    "好",
    "收到",
    "谢谢",
}

TERMINATE_TERMS = {
    "stop",
    "stop it",
    "that's all",
    "thats all",
    "no more",
    "done",
    "end",
    "结束",
    "别说了",
    "停",
}

ELABORATE_TERMS = {
    "more info",
    "more information",
    "additional info",
    "additional information",
    "more details",
    "other details",
    "tell me more",
    "anything else",
    "do you have more information",
    "还有吗",
    "更多信息",
    "更多细节",
    "详细一点",
}

INQUIRY_HINTS = {
    "application",
    "applications",
    "price",
    "quote",
    "cost",
    "lead time",
    "timeline",
    "reactivity",
    "species",
    "target",
    "antigen",
    "validation",
    "protocol",
    "datasheet",
    "brochure",
    "document",
    "manual",
    "how to use",
    "how do i use",
    "workflow",
    "plan",
}

FILLER_TOKENS = {
    "ok",
    "okay",
    "thanks",
    "thank",
    "you",
    "got",
    "it",
    "please",
    "can",
    "you",
    "do",
    "have",
    "more",
    "info",
    "information",
    "details",
}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _extract_selection_candidate(query: str, candidate_options: list[str]) -> str:
    normalized = _normalize_text(query)
    if not normalized or not candidate_options:
        return ""

    for option in candidate_options:
        option_norm = _normalize_text(option)
        if normalized == option_norm:
            return option

    id_match = re.search(r"\b(?:id|catalog(?: number| no)?)\s*[:#]?\s*([a-z0-9-]+)\b", normalized)
    if id_match:
        candidate = id_match.group(1).upper()
        for option in candidate_options:
            if option.upper() == candidate:
                return option

    if len(normalized.split()) <= 6:
        for option in candidate_options:
            option_norm = _normalize_text(option)
            if option_norm and option_norm in normalized:
                return option

    return ""


def _has_information_gain(query: str) -> bool:
    normalized = _normalize_text(query)
    if not normalized:
        return False
    if "?" in query:
        return True
    if _has_any(normalized, INQUIRY_HINTS):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    meaningful = [token for token in tokens if token not in FILLER_TOKENS]
    return len(meaningful) >= 2


def resolve_dialogue_act(agent_input, route, signal_ctx: dict) -> dict:
    raw_query = _normalize_text(signal_ctx.get("raw_query") or agent_input.original_query or agent_input.query)
    pending = agent_input.routing_memory.session_payload.pending_clarification
    candidate_options = list(pending.candidate_options or [])

    if pending.field == "product_selection":
        selected = _extract_selection_candidate(raw_query, candidate_options)
        if selected:
            return {
                "dialogue_act": "SELECTION",
                "confidence": 0.99,
                "reason": "The user reply matches one of the pending product-selection candidates.",
                "selection_value": selected,
            }

    if raw_query in TERMINATE_TERMS:
        return {
            "dialogue_act": "TERMINATE",
            "confidence": 0.97,
            "reason": "The user explicitly asked to stop or end the current exchange.",
        }

    if raw_query in ACK_TERMS:
        return {
            "dialogue_act": "ACKNOWLEDGE",
            "confidence": 0.95,
            "reason": "The user only acknowledged the prior response without adding a new request.",
        }

    if _has_any(raw_query, ACK_TERMS):
        if _has_information_gain(raw_query):
            return {
                "dialogue_act": "INQUIRY",
                "confidence": 0.84,
                "reason": "The user mixed acknowledgement language with a new business request.",
            }
        return {
            "dialogue_act": "ACKNOWLEDGE",
            "confidence": 0.82,
            "reason": "The user response is primarily an acknowledgement.",
        }

    if raw_query in ELABORATE_TERMS or _has_any(raw_query, ELABORATE_TERMS):
        return {
            "dialogue_act": "ELABORATE",
            "confidence": 0.92,
            "reason": "The user asked for more detail on the current topic.",
        }

    if _has_information_gain(raw_query):
        return {
            "dialogue_act": "INQUIRY",
            "confidence": 0.76,
            "reason": "The user added a fresh question or domain-specific request.",
        }

    return {
        "dialogue_act": "UNKNOWN",
        "confidence": 0.3,
        "reason": "No strong dialogue-act signal was detected.",
    }
