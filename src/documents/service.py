from __future__ import annotations

from typing import Any

from .retrieval import DOCUMENT_CATALOG_PATH, DOCUMENT_ROOT
from .selection import run_document_selection


def lookup_documents(
    *,
    query: str,
    catalog_numbers: list[str] | None = None,
    product_names: list[str] | None = None,
    document_names: list[str] | None = None,
    business_line_hint: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    result = run_document_selection(
        query=query,
        catalog_numbers=catalog_numbers,
        product_names=product_names,
        document_names=document_names,
        business_line_hint=business_line_hint,
        top_k=top_k,
    )
    return {
        **result,
        "document_root": str(DOCUMENT_ROOT),
        "catalog_path": str(DOCUMENT_CATALOG_PATH),
    }
