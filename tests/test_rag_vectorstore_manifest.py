from __future__ import annotations

from pathlib import Path
import json
import sys

from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.vectorstore import (
    _build_index_manifest,
    _load_index_manifest,
    _manifests_match,
    _source_documents_digest,
    _stable_chunk_key,
)


def test_source_documents_digest_changes_when_content_changes() -> None:
    documents_a = [
        Document(
            page_content="alpha content",
            metadata={"source_path": "/tmp/a.txt", "document_type": "service_page"},
        )
    ]
    documents_b = [
        Document(
            page_content="beta content",
            metadata={"source_path": "/tmp/a.txt", "document_type": "service_page"},
        )
    ]

    digest_a, count_a = _source_documents_digest(documents_a)
    digest_b, count_b = _source_documents_digest(documents_b)

    assert count_a == 1
    assert count_b == 1
    assert digest_a != digest_b


def test_stable_chunk_key_does_not_depend_on_global_index() -> None:
    chunk_a = Document(
        page_content="same content",
        metadata={
            "source_path": "/tmp/a.txt",
            "structural_tag": "workflow_step",
            "chunk_label": "Step A",
        },
    )
    chunk_b = Document(
        page_content="same content",
        metadata={
            "source_path": "/tmp/a.txt",
            "structural_tag": "workflow_step",
            "chunk_label": "Step A",
        },
    )

    assert _stable_chunk_key(chunk_a) == _stable_chunk_key(chunk_b)


def test_manifest_match_requires_source_and_chunking_consistency() -> None:
    documents = [
        Document(
            page_content="alpha content",
            metadata={"source_path": "/tmp/a.txt", "document_type": "service_page"},
        )
    ]
    manifest = _build_index_manifest(documents=documents)
    assert _manifests_match(manifest, manifest) is True

    changed_source = dict(manifest)
    changed_source["source_digest"] = "different"
    assert _manifests_match(changed_source, manifest) is False

    changed_chunking = dict(manifest)
    changed_chunking["chunking_digest"] = "different"
    assert _manifests_match(changed_chunking, manifest) is False


def test_load_index_manifest_round_trip(tmp_path: Path) -> None:
    manifest_path = tmp_path / "index_manifest.json"
    manifest = {
        "schema_version": "rag_index_v1",
        "collection_name": "test_collection",
        "embedding_model": "text-embedding-3-small",
        "chunking_digest": "abc",
        "source_digest": "def",
        "fingerprint": "xyz",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = _load_index_manifest(manifest_path)
    assert loaded == manifest
