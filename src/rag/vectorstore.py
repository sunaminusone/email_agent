from functools import lru_cache
from pathlib import Path
import hashlib
import re
from typing import Dict, List

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.config import get_embeddings

RAG_SOURCE_DIR = Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_files")
CHROMA_DIR = Path("/Users/promab/anaconda_projects/email_agent/data/processed/chroma_rag")
IGNORED_NAMES = {".DS_Store"}
IGNORED_PARTS = {".ipynb_checkpoints"}
SUPPORTED_SUFFIXES = {".txt", ".md"}
COLLECTION_NAME = "email_agent_rag_v4_hybrid"
STRUCTURED_TAGS = [
    "DOCUMENT",
    "SECTION",
    "PRODUCT_GROUP",
    "PRODUCT",
    "CAPABILITY",
    "WORKFLOW",
    "CELL_TYPES",
]
HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
)
RECURSIVE_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=900,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", "; ", " "],
)


def _normalize_text(text: str) -> str:
    normalized = text.lower().strip()
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_key_values(block_text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    current_key = ""
    current_lines: List[str] = []

    for raw_line in block_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        key_match = re.match(r"^([A-Za-z0-9_ /()-]+):\s*(.*)$", line)
        if key_match:
            if current_key:
                fields[current_key] = "\n".join(current_lines).strip()
            current_key = _normalize_text(key_match.group(1)).replace(" ", "_")
            current_lines = [key_match.group(2).strip()]
            continue
        if current_key:
            current_lines.append(line.strip())

    if current_key:
        fields[current_key] = "\n".join(current_lines).strip()
    return fields


def _infer_business_line(file_name: str) -> str:
    normalized = _normalize_text(file_name)
    if "car t" in normalized or "car nk" in normalized:
        return "car_t"
    if "mrna" in normalized or "lnp" in normalized:
        return "mrna_lnp"
    if "antibody" in normalized:
        return "antibody"
    return "unknown"


def _infer_document_type(file_name: str) -> str:
    normalized = _normalize_text(file_name)
    if "brochure" in normalized:
        return "brochure"
    if "flyer" in normalized:
        return "flyer"
    if "booklet" in normalized:
        return "booklet"
    return "technical_text"


def _load_source_documents() -> List[Document]:
    documents: List[Document] = []
    if not RAG_SOURCE_DIR.exists():
        return documents

    for path in sorted(RAG_SOURCE_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.name in IGNORED_NAMES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source_path": str(path),
                    "file_name": path.name,
                    "document_type": _infer_document_type(path.name),
                    "business_line": _infer_business_line(path.name),
                    "source_format": path.suffix.lower().lstrip("."),
                },
            )
        )
    return documents


def _split_markdown_document(document: Document) -> List[Document]:
    header_docs = HEADER_SPLITTER.split_text(document.page_content)
    if not header_docs:
        header_docs = [Document(page_content=document.page_content, metadata={})]

    split_docs: List[Document] = []
    for index, header_doc in enumerate(header_docs):
        merged_metadata = {**document.metadata, **header_doc.metadata}
        merged_metadata["chunk_strategy"] = "markdown_recursive"
        merged_metadata["structural_tag"] = "markdown_section"
        merged_metadata["structural_order"] = index

        nested_docs = RECURSIVE_SPLITTER.split_documents(
            [Document(page_content=header_doc.page_content, metadata=merged_metadata)]
        )
        if nested_docs:
            split_docs.extend(nested_docs)
        else:
            split_docs.append(Document(page_content=header_doc.page_content, metadata=merged_metadata))
    return split_docs


def _build_structured_txt_chunk(tag: str, body: str, base_metadata: Dict[str, str], order: int) -> List[Document]:
    normalized_body = _normalize_whitespace(body)
    if not normalized_body:
        return []

    fields = _parse_key_values(normalized_body)
    label = fields.get("title") or fields.get("name") or fields.get("catalog_no") or tag.lower()
    if tag == "SECTION":
        content = "\n".join(
            value
            for value in [fields.get("title"), fields.get("subtitle"), fields.get("summary"), fields.get("content"), fields.get("note")]
            if value
        ).strip()
    else:
        content = "\n".join(
            value
            for value in [
                fields.get("name"),
                fields.get("catalog_no"),
                fields.get("type"),
                fields.get("group_type"),
                fields.get("summary"),
                fields.get("content"),
            ]
            if value
        ).strip() or normalized_body

    chunk_text = f"{tag.title()}: {label}\n{content or normalized_body}"
    metadata = {
        **base_metadata,
        "chunk_strategy": "structured_txt",
        "structural_tag": tag.lower(),
        "structural_order": order,
        "chunk_label": label,
    }

    for key in ("title", "name", "catalog_no", "type", "group_type", "subtitle"):
        if fields.get(key):
            metadata[key] = fields[key]

    # Keep structure-first chunking for txt. Only fall back to recursive split
    # when a single structural block is unusually large.
    if len(chunk_text) <= 1800:
        return [Document(page_content=chunk_text, metadata=metadata)]

    oversized_docs = RECURSIVE_SPLITTER.split_documents([Document(page_content=chunk_text, metadata=metadata)])
    if not oversized_docs:
        return [Document(page_content=chunk_text, metadata=metadata)]
    return oversized_docs


def _split_structured_txt_document(document: Document) -> List[Document]:
    matches = []
    for tag in STRUCTURED_TAGS:
        pattern = re.compile(rf"\[{tag}\]\s*(.*?)\s*\[END_{tag}\]", re.S)
        for match in pattern.finditer(document.page_content):
            matches.append((match.start(), tag, match.group(1)))
    matches.sort(key=lambda item: item[0])

    if not matches:
        fallback = Document(
            page_content=document.page_content,
            metadata={**document.metadata, "chunk_strategy": "structured_txt_fallback", "structural_tag": "full_document"},
        )
        return [fallback]

    chunks: List[Document] = []
    for order, (_, tag, body) in enumerate(matches):
        block_chunks = _build_structured_txt_chunk(
            tag,
            body,
            document.metadata,
            order,
        )
        chunks.extend(block_chunks)
    return chunks


def _split_documents(documents: List[Document]) -> List[Document]:
    chunks: List[Document] = []

    for document in documents:
        source_format = document.metadata.get("source_format")
        if source_format == "md":
            chunks.extend(_split_markdown_document(document))
        elif source_format == "txt":
            chunks.extend(_split_structured_txt_document(document))
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
