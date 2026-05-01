"""Tests for #1.6: surface S3 presigned-URL failures instead of dropping silently.

When S3 minting fails, selection.py used to set `document_url = ""` and let
the match fall through. Frontend then filters out matches with empty
document_url, so the CSR sees "no documents" even though documents WERE
found — they just had broken URLs. The fix tracks `url_failures` so the
tool layer can escalate to `partial_result` with an explicit error.
"""
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.documents.selection import run_document_selection
from src.tools.documents.documentation_tool import execute_document_lookup
from src.tools.models import ToolRequest


# ---------------------------------------------------------------------------
# selection.py — tracks url_failures and keeps matches
# ---------------------------------------------------------------------------

def _stub_inventory():
    """Two service documents, each with a usable storage_url."""
    return [
        {
            "file_name": "datasheet-a.pdf",
            "source_path": "s3://promab-docs/a.pdf",
            "storage_url": "s3://promab-docs/a.pdf",
            "document_type": "datasheet",
            "business_line": "antibody",
            "normalized_business_line": "antibody",
            "product_scope": "service_line",
            "product_name": "Anti-CD3",
            "catalog_no": "",
            "title": "Anti-CD3 Datasheet",
            "normalized_name": "anti cd3 datasheet",
            "tokens": ["anti", "cd3", "datasheet"],
        },
        {
            "file_name": "flyer-b.pdf",
            "source_path": "s3://promab-docs/b.pdf",
            "storage_url": "s3://promab-docs/b.pdf",
            "document_type": "datasheet",
            "business_line": "antibody",
            "normalized_business_line": "antibody",
            "product_scope": "service_line",
            "product_name": "Anti-CD3",
            "catalog_no": "",
            "title": "Anti-CD3 Flyer",
            "normalized_name": "anti cd3 flyer",
            "tokens": ["anti", "cd3", "flyer"],
        },
    ]


def test_selection_records_url_failures_when_presigning_throws():
    def boom(_storage_url):
        raise RuntimeError("S3 access denied")

    with patch(
        "src.documents.selection.document_catalog_inventory",
        return_value=_stub_inventory(),
    ), patch("src.documents.selection.generate_presigned_document_url", boom):
        output = run_document_selection(
            query="anti cd3 datasheet",
            product_names=["Anti-CD3"],
            business_line_hint="antibody",
        )

    assert len(output["matches"]) >= 1
    assert all(m["document_url"] == "" for m in output["matches"])
    assert len(output["url_failures"]) == len(output["matches"])
    assert any("S3 access denied" in failure for failure in output["url_failures"])


def test_selection_clean_run_has_no_url_failures():
    with patch(
        "src.documents.selection.document_catalog_inventory",
        return_value=_stub_inventory(),
    ), patch(
        "src.documents.selection.generate_presigned_document_url",
        side_effect=lambda url: f"https://signed.example/{url.rsplit('/', 1)[-1]}?sig=ok",
    ):
        output = run_document_selection(
            query="anti cd3 datasheet",
            product_names=["Anti-CD3"],
            business_line_hint="antibody",
        )

    assert len(output["matches"]) >= 1
    assert all(m["document_url"].startswith("https://signed.example/") for m in output["matches"])
    assert output["url_failures"] == []


# ---------------------------------------------------------------------------
# documentation_tool.py — escalates to partial_result on url_failures
# ---------------------------------------------------------------------------

def test_documentation_tool_returns_partial_when_all_urls_fail():
    """When every match has a broken URL, the CSR must see partial + error."""
    def boom(_storage_url):
        raise RuntimeError("boto3 missing")

    with patch(
        "src.documents.selection.document_catalog_inventory",
        return_value=_stub_inventory(),
    ), patch("src.documents.selection.generate_presigned_document_url", boom):
        request = ToolRequest(
            tool_name="document_lookup_tool",
            query="anti cd3 datasheet",
        )
        result = execute_document_lookup(request)

    assert result.status == "partial"
    assert len(result.primary_records) >= 1
    assert any("Failed to mint presigned URL" in err for err in result.errors)
    assert result.structured_facts["url_failures"]


def test_documentation_tool_returns_ok_when_urls_work():
    with patch(
        "src.documents.selection.document_catalog_inventory",
        return_value=_stub_inventory(),
    ), patch(
        "src.documents.selection.generate_presigned_document_url",
        side_effect=lambda url: f"https://signed.example/{url.rsplit('/', 1)[-1]}?sig=ok",
    ):
        request = ToolRequest(
            tool_name="document_lookup_tool",
            query="anti cd3 datasheet",
        )
        result = execute_document_lookup(request)

    assert result.status == "ok"
    assert len(result.primary_records) >= 1
    assert result.errors == []
    assert result.structured_facts["url_failures"] == []


# ---------------------------------------------------------------------------
# document_catalog_inventory: PG failures must propagate, not silently empty
# ---------------------------------------------------------------------------

def test_documentation_tool_surfaces_inventory_pg_failure_as_error():
    """Previously document_catalog_inventory returned [] on any PG exception
    and the lru_cache would freeze the empty result for the rest of the
    process. The CSR saw 'no documents' instead of 'PG is down'. Now the
    exception propagates to the tool wrapper, which already surfaces the
    underlying error text via error_result."""
    def boom(**kwargs):
        raise ConnectionError("PG connect timeout: server unreachable")

    with patch("src.documents.service.run_document_selection", boom):
        request = ToolRequest(
            tool_name="document_lookup_tool",
            query="anti cd3 datasheet",
        )
        result = execute_document_lookup(request)

    assert result.status == "error"
    assert any("PG connect timeout" in err for err in result.errors)


def test_document_catalog_inventory_does_not_cache_failures():
    """When the PG query raises, lru_cache should not store the failure
    so a subsequent call (after PG recovers) tries again."""
    from src.documents.retrieval.shared import document_catalog_inventory

    document_catalog_inventory.cache_clear()

    call_count = {"n": 0}

    def fake_psycopg_connect(*args, **kwargs):
        call_count["n"] += 1
        raise ConnectionError("transient PG outage")

    helpers = {
        "infer_document_type": lambda x: "datasheet",
        "normalize_text": lambda x: str(x).lower(),
        "tokenize": lambda x: str(x).lower().split(),
        "normalize_business_line": lambda x: str(x).lower(),
    }

    with patch("src.documents.retrieval.shared.psycopg.connect", fake_psycopg_connect):
        try:
            document_catalog_inventory(**helpers)
        except ConnectionError:
            pass
        try:
            document_catalog_inventory(**helpers)
        except ConnectionError:
            pass

    document_catalog_inventory.cache_clear()
    assert call_count["n"] == 2  # both calls hit PG, no cached empty result
