from functools import lru_cache
from pathlib import Path
import hashlib
import shutil
import time
from typing import List

from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.config import get_embeddings
from src.rag.service_page_ingestion import load_service_page_documents

CHROMA_DIR = Path("/Users/promab/anaconda_projects/email_agent/data/processed/chroma_rag_service_pages")
COLLECTION_NAME = "email_agent_rag_v7_service_pages_only"
HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
)
RECURSIVE_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=900,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", "; ", " "],
)


def _load_source_documents() -> List[Document]:
    return load_service_page_documents()


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
                chunks.extend(nested_docs or [Document(page_content=header_doc.page_content, metadata=merged_metadata)])
        else:
            chunks.extend(RECURSIVE_SPLITTER.split_documents([document]))

    finalized: List[Document] = []
    for index, chunk in enumerate(chunks):
        source_path = chunk.metadata.get("source_path", "")
        digest = hashlib.md5(f"{source_path}:{index}:{chunk.page_content[:120]}".encode("utf-8")).hexdigest()
        chunk.metadata["chunk_id"] = index
        chunk.metadata["chunk_key"] = digest
        finalized.append(chunk)
    return finalized


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    embeddings = get_embeddings()
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    store = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )

    existing = store.get(include=[])
    if existing.get("ids"):
        return store

    source_documents = _load_source_documents()
    if not source_documents:
        return store

    chunks = _split_documents(source_documents)
    ids = [chunk.metadata["chunk_key"] for chunk in chunks]
    store.add_documents(chunks, ids=ids)
    return store


def rebuild_vectorstore() -> Chroma:
    get_vectorstore.cache_clear()
    embeddings = get_embeddings()

    last_error: Exception | None = None
    for _ in range(2):
        try:
            SharedSystemClient.clear_system_cache()
            if CHROMA_DIR.exists():
                shutil.rmtree(CHROMA_DIR)
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            store = Chroma(
                collection_name=COLLECTION_NAME,
                persist_directory=str(CHROMA_DIR),
                embedding_function=embeddings,
            )
            source_documents = _load_source_documents()
            if source_documents:
                chunks = _split_documents(source_documents)
                ids = [chunk.metadata["chunk_key"] for chunk in chunks]
                store.add_documents(chunks, ids=ids)
            get_vectorstore.cache_clear()
            SharedSystemClient.clear_system_cache()
            return store
        except Exception as exc:
            last_error = exc
            SharedSystemClient.clear_system_cache()
            time.sleep(0.2)

    assert last_error is not None
    raise last_error
