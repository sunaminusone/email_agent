from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


DEFAULT_COMPANY = "ProMab"
DEFAULT_SECTION_CHUNK_POLICY = "section_per_chunk"
DEFAULT_EMBEDDING_SEPARATOR = " | "


class IngestionSection(BaseModel):
    company: str = Field(default=DEFAULT_COMPANY, description="Owning company or brand for the section.")
    title: str = Field(default="", description="Human-readable section title.")
    body: str = Field(default="", description="Main section content used for chunking and embedding.")
    section_type: str = Field(default="general", description="Section category such as ingestion_guidance, service_flyer, or product_overview.")
    tags: List[str] = Field(default_factory=list, description="Structured tags used for retrieval filtering and embedding enrichment.")
    source_path: str = Field(default="", description="Optional source file path or source document reference.")
    business_line: str = Field(default="", description="Business-line hint such as antibody, car_t_car_nk, mrna_lnp, or other_service.")
    entity_type: str = Field(default="", description="Entity type such as product, service, or document.")
    entity_name: str = Field(default="", description="Canonical product or service name when available.")
    catalog_no: str = Field(default="", description="Catalog number when available.")
    document_type: str = Field(default="", description="Document type such as flyer, brochure, datasheet, or protocol.")
    structural_tag: str = Field(default="section", description="Structural tag used by retrieval and ranking logic.")


def normalize_tags(tags: List[str] | None) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for tag in tags or []:
        cleaned = str(tag or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def build_embedding_string(section: IngestionSection) -> str:
    tags = normalize_tags([section.company, *section.tags])
    parts = [
        f"company: {section.company or DEFAULT_COMPANY}",
        f"tags: {', '.join(tags)}" if tags else "",
        f"title: {section.title}" if section.title else "",
        f"body: {section.body}" if section.body else "",
    ]
    return DEFAULT_EMBEDDING_SEPARATOR.join(part for part in parts if part)


def build_chunk_metadata(section: IngestionSection, *, chunk_index: int = 0, chunk_key: str = "") -> Dict[str, Any]:
    tags = normalize_tags([section.company, *section.tags])
    metadata: Dict[str, Any] = {
        "company": section.company or DEFAULT_COMPANY,
        "title": section.title,
        "section_type": section.section_type,
        "tags": tags,
        "source_path": section.source_path,
        "business_line": section.business_line,
        "entity_type": section.entity_type,
        "entity_name": section.entity_name,
        "catalog_no": section.catalog_no,
        "document_type": section.document_type or "technical_text",
        "structural_tag": section.structural_tag or "section",
        "chunk_strategy": DEFAULT_SECTION_CHUNK_POLICY,
        "chunk_index": chunk_index,
    }
    if chunk_key:
        metadata["chunk_key"] = chunk_key
    return metadata


PROMAB_INGESTION_NOTES = IngestionSection(
    company="ProMab",
    title="RAG Ingestion Notes",
    section_type="ingestion_guidance",
    tags=["RAG", "chunking", "embedding", "metadata", "tags", "retrieval", "ProMab"],
    body=(
        "Recommended embedding input pattern: combine tags + title + body into one embedding string; "
        "preserve company: ProMab in each chunk or metadata; keep each section as a separate chunk candidate; "
        "use structured fields for section_type and tags to improve filtering and retrieval. "
        "Example embedding string pattern: "
        "\"company: ProMab | tags: ProMab, CAR-T, CAR-NK, cell therapy | title: Service Category - CAR-T/CAR-NK Development | "
        "body: ProMab provides Custom CAR-T Cell Development; Custom CAR-NK Cell Development; Custom CAR-Macrophage Cell Development; "
        "Custom Gamma Delta T Cell Development; Lentivirus Production; Licensing CAR Technology.\""
    ),
    structural_tag="ingestion_guidance",
)


__all__ = [
    "DEFAULT_COMPANY",
    "DEFAULT_SECTION_CHUNK_POLICY",
    "DEFAULT_EMBEDDING_SEPARATOR",
    "IngestionSection",
    "PROMAB_INGESTION_NOTES",
    "build_chunk_metadata",
    "build_embedding_string",
    "normalize_tags",
]
