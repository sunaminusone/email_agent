from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


RERANK_MODEL_NAME = "BAAI/bge-reranker-base"
RERANK_MAX_LENGTH = 512


@lru_cache(maxsize=1)
def _get_reranker_components() -> tuple[Any, Any]:
    tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(RERANK_MODEL_NAME)
    model.eval()
    return tokenizer, model


def rerank_matches(query: str, matches: List[Dict[str, Any]], *, top_k: int) -> List[Dict[str, Any]]:
    if not matches:
        return []

    tokenizer, model = _get_reranker_components()
    pair_count = min(len(matches), max(top_k * 3, 12))
    candidates = matches[:pair_count]

    queries = [query] * len(candidates)
    documents = [candidate["content"] for candidate in candidates]
    inputs = tokenizer(
        queries,
        documents,
        padding=True,
        truncation=True,
        max_length=RERANK_MAX_LENGTH,
        return_tensors="pt",
    )

    with torch.no_grad():
        logits = model(**inputs).logits.view(-1).tolist()

    reranked: List[Dict[str, Any]] = []
    for candidate, rerank_score in zip(candidates, logits):
        reranked.append(
            {
                **candidate,
                "rerank_score": float(rerank_score),
            }
        )

    reranked.sort(key=lambda item: (-item["rerank_score"], item["score"]))

    remaining = matches[pair_count:]
    if remaining:
        reranked.extend(remaining)

    return reranked[:top_k]


__all__ = ["RERANK_MODEL_NAME", "rerank_matches"]
