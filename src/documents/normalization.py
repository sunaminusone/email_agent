from __future__ import annotations

import re


DOCUMENT_TYPE_PATTERNS = {
    "datasheet": ["datasheet", "data sheet"],
    "brochure": ["brochure"],
    "flyer": ["flyer"],
    "booklet": ["booklet"],
    "protocol": ["protocol"],
    "coa": ["coa", "certificate of analysis"],
    "sds": ["sds", "safety data sheet", "msds"],
    "validation": ["validation"],
}

TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "can",
    "doc",
    "document",
    "documents",
    "for",
    "from",
    "give",
    "i",
    "info",
    "information",
    "me",
    "need",
    "of",
    "please",
    "provide",
    "send",
    "share",
    "the",
    "to",
    "with",
}


def normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = lowered.replace("_", " ").replace("-", " ")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [
        token
        for token in re.split(r"[^a-z0-9]+", normalized)
        if len(token) >= 2 and token not in TOKEN_STOPWORDS
    ]


def detect_requested_document_types(query: str, document_names: list[str]) -> list[str]:
    joined = " ".join([query] + document_names)
    normalized = normalize_text(joined)
    matched = []
    for doc_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            matched.append(doc_type)
    return matched


def infer_document_type_from_name(file_name: str) -> str:
    normalized = normalize_text(file_name)
    for doc_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return doc_type
    return "general"


def document_type_matches(item_type: str, requested_types: list[str]) -> bool:
    if not requested_types:
        return False
    normalized_item_type = normalize_text(item_type)
    normalized_requested = {normalize_text(value) for value in requested_types}
    if normalized_item_type in normalized_requested:
        return True
    if normalized_item_type == "service flyer" and "flyer" in normalized_requested:
        return True
    return False


def normalize_business_line(value: str) -> str:
    normalized = normalize_text(value)
    normalized = normalized.replace("/", " ").replace("&", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def business_line_matches(hint: str, item_value: str) -> bool:
    normalized_hint = normalize_business_line(hint)
    normalized_item = normalize_business_line(item_value)
    if not normalized_hint or not normalized_item:
        return False
    return normalized_hint == normalized_item or normalized_hint in normalized_item or normalized_item in normalized_hint
