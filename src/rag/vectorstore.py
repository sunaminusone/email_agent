from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import shutil
import time
from typing import Any, List

from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.config import get_embeddings
from src.rag.service_page_ingestion import load_service_page_documents

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = _PROJECT_ROOT / "data" / "processed" / "chroma_rag_service_pages"
COLLECTION_NAME = "email_agent_rag_v7_service_pages_only"
INDEX_MANIFEST_PATH = CHROMA_DIR / "index_manifest.json"
INDEX_SCHEMA_VERSION = "rag_index_v1"
HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
)
RECURSIVE_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=900,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", "; ", " "],
)


def _load_source_documents() -> List[Document]:
    return list(load_service_page_documents())


def _stable_chunk_key(chunk: Document) -> str:
    source_path = str(chunk.metadata.get("source_path", "") or "")
    structural_tag = str(chunk.metadata.get("structural_tag", "") or "")
    chunk_label = str(chunk.metadata.get("chunk_label", "") or "")
    content_digest = hashlib.md5(chunk.page_content.encode("utf-8")).hexdigest()
    key_payload = f"{source_path}|{structural_tag}|{chunk_label}|{content_digest}"
    return hashlib.md5(key_payload.encode("utf-8")).hexdigest()


def _split_documents(documents: List[Document]) -> List[Document]:
    chunks: List[Document] = []

    for document in documents:
        if document.metadata.get("prechunked"):
            chunks.append(document)
            continue
        source_format = document.metadata.get("source_format")
        if source_format == "md":
            header_docs = HEADER_SPLITTER.split_text(document.page_content)
            if not header_docs:
                header_docs = [Document(page_content=document.page_content, metadata={})]
            for index, header_doc in enumerate(header_docs):
                merged_metadata = {**document.metadata, **header_doc.metadata}
                merged_metadata["chunk_strategy"] = "markdown_recursive"
                merged_metadata["structural_tag"] = "markdown_section"
                merged_metadata["structural_order"] = index
                nested_docs = RECURSIVE_SPLITTER.split_documents(
                    [Document(page_content=header_doc.page_content, metadata=merged_metadata)]
                )
                chunks.extend(
                    nested_docs or [Document(page_content=header_doc.page_content, metadata=merged_metadata)]
                )
        else:
            chunks.extend(RECURSIVE_SPLITTER.split_documents([document]))

    finalized: List[Document] = []
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = index
        chunk.metadata["chunk_key"] = _stable_chunk_key(chunk)
        finalized.append(chunk)
    return finalized


def _chunking_config() -> dict[str, Any]:
    return {
        "header_splitter": [["#", "h1"], ["##", "h2"], ["###", "h3"]],
        "recursive_chunk_size": RECURSIVE_SPLITTER._chunk_size,
        "recursive_chunk_overlap": RECURSIVE_SPLITTER._chunk_overlap,
        "recursive_separators": list(RECURSIVE_SPLITTER._separators),
    }


def _digest_jsonable(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def _source_documents_digest(documents: List[Document]) -> tuple[str, int]:
    normalized_docs = []
    for document in documents:
        normalized_docs.append(
            {
                "source_path": str(document.metadata.get("source_path", "") or ""),
                "document_type": str(document.metadata.get("document_type", "") or ""),
                "section_type": str(document.metadata.get("section_type", "") or ""),
                "chunk_label": str(document.metadata.get("chunk_label", "") or ""),
                "content_digest": hashlib.md5(document.page_content.encode("utf-8")).hexdigest(),
            }
        )
    normalized_docs.sort(
        key=lambda item: (
            item["source_path"],
            item["document_type"],
            item["section_type"],
            item["chunk_label"],
            item["content_digest"],
        )
    )
    return _digest_jsonable(normalized_docs), len(normalized_docs)


def _build_index_manifest(*, documents: List[Document]) -> dict[str, Any]:
    source_digest, source_count = _source_documents_digest(documents)
    chunking_config = _chunking_config()
    embedding_model = "text-embedding-3-small"

    manifest = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "collection_name": COLLECTION_NAME,
        "embedding_model": embedding_model,
        "chunking": chunking_config,
        "chunking_digest": _digest_jsonable(chunking_config),
        "source_documents_count": source_count,
        "source_digest": source_digest,
    }
    manifest["fingerprint"] = _digest_jsonable(manifest)
    return manifest


def _load_index_manifest(path: Path = INDEX_MANIFEST_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_index_manifest(manifest: dict[str, Any], path: Path = INDEX_MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifests_match(stored: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not stored:
        return False
    required_keys = (
        "schema_version",
        "collection_name",
        "embedding_model",
        "chunking_digest",
        "source_digest",
        "fingerprint",
    )
    return all(stored.get(key) == current.get(key) for key in required_keys)


def _create_store(embeddings: Any) -> Chroma:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )


def _clear_vectorstore_dir() -> None:
    SharedSystemClient.clear_system_cache()
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def _populate_store(
    *,
    store: Chroma,
    documents: List[Document],
    manifest: dict[str, Any],
) -> Chroma:
    if documents:
        chunks = _split_documents(documents)
        ids = [chunk.metadata["chunk_key"] for chunk in chunks]
        store.add_documents(chunks, ids=ids)
    _write_index_manifest(manifest)
    return store


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    embeddings = get_embeddings()
    source_documents = _load_source_documents()
    current_manifest = _build_index_manifest(documents=source_documents)

    store = _create_store(embeddings)
    existing = store.get(include=[])
    stored_manifest = _load_index_manifest()

    if existing.get("ids") and _manifests_match(stored_manifest, current_manifest):
        return store

    return rebuild_vectorstore(
        source_documents=source_documents,
        manifest=current_manifest,
    )


def rebuild_vectorstore(
    *,
    source_documents: List[Document] | None = None,
    manifest: dict[str, Any] | None = None,
) -> Chroma:
    get_vectorstore.cache_clear()
    embeddings = get_embeddings()
    source_documents = source_documents if source_documents is not None else _load_source_documents()
    manifest = manifest if manifest is not None else _build_index_manifest(documents=source_documents)

    last_error: Exception | None = None
    for _ in range(2):
        try:
            _clear_vectorstore_dir()
            store = _create_store(embeddings)
            _populate_store(store=store, documents=source_documents, manifest=manifest)
            get_vectorstore.cache_clear()
            SharedSystemClient.clear_system_cache()
            return store
        except Exception as exc:
            last_error = exc
            SharedSystemClient.clear_system_cache()
            time.sleep(0.2)

    assert last_error is not None
    raise last_error


__all__ = [
    "CHROMA_DIR",
    "COLLECTION_NAME",
    "INDEX_MANIFEST_PATH",
    "INDEX_SCHEMA_VERSION",
    "get_vectorstore",
    "rebuild_vectorstore",
    "_build_index_manifest",
    "_load_index_manifest",
    "_manifests_match",
    "_source_documents_digest",
    "_split_documents",
    "_stable_chunk_key",
]
