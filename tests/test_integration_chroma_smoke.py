"""Chroma collection smoke test for both vector stores.

Catches the silent failure mode where a missing or schema-drifted
``data/processed/chroma_*`` directory leaves ``get_vectorstore`` /
``get_threads_store`` returning an empty collection — production code
swallows the read, RAG returns zero matches, and CSR sees "no
historical thread / no document" with no error.

Run with ``pytest tests/test_integration_chroma_smoke.py --integration``.
"""
from __future__ import annotations

import pytest

from src.rag.historical_threads import (
    COLLECTION_NAME as HISTORICAL_COLLECTION_NAME,
    get_threads_store,
)
from src.rag.vectorstore import (
    COLLECTION_NAME as RAG_COLLECTION_NAME,
    get_vectorstore,
)

pytestmark = pytest.mark.integration


def test_rag_vectorstore_has_chunks() -> None:
    store = get_vectorstore()
    assert store._collection.name == RAG_COLLECTION_NAME
    count = store._collection.count()
    assert count > 0, f"{RAG_COLLECTION_NAME} is empty; reingest brochures/service pages"


def test_historical_threads_store_has_threads() -> None:
    store = get_threads_store()
    assert store._collection.name == HISTORICAL_COLLECTION_NAME
    count = store._collection.count()
    assert count > 0, (
        f"{HISTORICAL_COLLECTION_NAME} is empty; "
        "rerun scripts/ingest_historical_threads.py"
    )


def test_rag_vectorstore_similarity_search_returns_chunks() -> None:
    store = get_vectorstore()
    docs = store.similarity_search("antibody production service", k=3)
    assert docs, "similarity_search returned 0 docs for a known-good query"
    assert all(d.page_content for d in docs)


def test_historical_threads_similarity_search_returns_threads() -> None:
    store = get_threads_store()
    docs = store.similarity_search("stable cell line quote", k=3)
    assert docs, "similarity_search returned 0 docs for a known-good query"
    assert all(d.metadata.get("submission_id") for d in docs), (
        "expected submission_id metadata on every historical thread chunk"
    )
