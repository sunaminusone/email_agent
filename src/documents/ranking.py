from __future__ import annotations


def rank_document_matches(matches: list[dict], top_k: int) -> list[dict]:
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:top_k]
