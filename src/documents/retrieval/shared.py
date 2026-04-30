from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT_ROOT = _PROJECT_ROOT / "data" / "raw" / "pdf"
DOCUMENT_CATALOG_PATH = _PROJECT_ROOT / "data" / "processed" / "document_catalog.csv"
IGNORED_NAMES = {".DS_Store"}
IGNORED_PARTS = {".ipynb_checkpoints"}


def document_url(path: Path) -> str:
    relative_path = path.relative_to(DOCUMENT_ROOT).as_posix()
    return f"/documents/{quote(relative_path, safe='/')}"


def relative_document_url(relative_path: str) -> str:
    return f"/documents/{quote(relative_path, safe='/')}"


@lru_cache(maxsize=1)
def document_catalog_inventory(
    *,
    infer_document_type,
    normalize_text,
    tokenize,
    normalize_business_line,
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    if not DOCUMENT_CATALOG_PATH.exists():
        return inventory

    with DOCUMENT_CATALOG_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            row = {key: (value or "").strip() for key, value in raw_row.items()}
            relative_path = row.get("relative_path", "")
            if not relative_path:
                continue
            source_path = DOCUMENT_ROOT / relative_path
            if not source_path.exists():
                continue

            document_type = row.get("document_type", "") or infer_document_type(row.get("file_name", ""))
            business_line = row.get("business_line", "")
            title = row.get("title", "") or Path(relative_path).stem
            product_name = row.get("product_name", "")
            catalog_no = row.get("catalog_no", "").upper()
            product_scope = row.get("product_scope", "")
            search_blob = " ".join(
                part
                for part in [
                    row.get("file_name", ""),
                    title,
                    product_name,
                    business_line,
                    document_type,
                    product_scope,
                    row.get("notes", ""),
                    catalog_no,
                ]
                if part
            )
            inventory.append(
                {
                    "file_name": row.get("file_name", Path(relative_path).name),
                    "relative_path": relative_path,
                    "source_path": str(source_path),
                    "document_url": relative_document_url(relative_path),
                    "document_type": document_type,
                    "business_line": business_line,
                    "normalized_business_line": normalize_business_line(business_line),
                    "title": title,
                    "product_scope": product_scope,
                    "product_name": product_name,
                    "catalog_no": catalog_no,
                    "notes": row.get("notes", ""),
                    "normalized_name": normalize_text(search_blob),
                    "tokens": tokenize(search_blob),
                }
            )
    return inventory


@lru_cache(maxsize=1)
def document_inventory(
    *,
    infer_document_type,
    normalize_text,
    tokenize,
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    if not DOCUMENT_ROOT.exists():
        return inventory

    for path in DOCUMENT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name in IGNORED_NAMES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() != ".pdf":
            continue

        inventory.append(
            {
                "file_name": path.name,
                "source_path": str(path),
                "document_url": document_url(path),
                "document_type": infer_document_type(path.name),
                "normalized_name": normalize_text(path.stem),
                "tokens": tokenize(path.stem),
            }
        )
    return inventory
