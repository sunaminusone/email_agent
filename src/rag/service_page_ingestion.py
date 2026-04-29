from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Set

from langchain_core.documents import Document

from src.rag.ingestion_config import IngestionSection, build_chunk_metadata, build_embedding_string, normalize_tags


SERVICE_PAGE_SOURCE_DIRS = [
    Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk"),
    Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/mrna-lnp"),
    Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/antibody"),
    Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/cell-based-assays"),
    Path("/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/protein-expression"),
]
# Backward-compatible alias for older imports; the retriever now reads from all
# directories listed in SERVICE_PAGE_SOURCE_DIRS.
SERVICE_PAGE_SOURCE_DIR = SERVICE_PAGE_SOURCE_DIRS[0]
SECTION_PATTERN = re.compile(r"\[SECTION\]\s*(.*?)\s*\[END_SECTION\]", re.S)
DOCUMENT_PATTERN = re.compile(r"\[DOCUMENT\]\s*(.*?)\s*\[END_DOCUMENT\]", re.S)
SERVICE_PAGE_FILE_PATTERN = re.compile(r"promab_.*_rag_ready(?:_.*)?\.txt$", re.I)
_METADATA_FIELDS: Set[str] = {
    "company",
    "service_name",
    "document_type",
    "page_title",
    "source_url",
    "service_line",
    "entity_type",
    "business_line",
    "subcategory",
    "section_type",
    "section_title",
    "tags",
    "retrieval_priority",
    "evidence_level",
    "topic_group",
    "relation_type",
    "parent_service",
    "parent_section",
    "parent_section_type",
    "plan_name",
    "phase_name",
    "phase_role",
    "parent_phase",
    "milestone_name",
    "week_range",
    "step_name",
    "step",
    "previous_step",
    "next_step",
    "duration_weeks",
    "optional",
    "price_usd",
    "price_usd_min",
    "price_usd_max",
    "price_note",
    "pricing_tier",
    "unit",
    "unit_price_usd",
    "setup_fee_usd",
    "stage_type",
}
EXPLICIT_SUBCHUNK_SECTION_TYPES = {"plan_summary", "service_phase", "workflow_step"}
# SKU tables served by the structured catalog pipeline (catalog_lookup_tool,
# Excel-backed product_registry). Strip them from the RAG parent section body
# so long SKU listings don't dilute the service-level embedding.
_RAW_STRUCTURED_FIELDS: Set[str] = {"products"}


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _normalize_key(raw_key: str) -> str:
    normalized = raw_key.strip().lower()
    normalized = normalized.replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def _parse_key_values(block_text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    current_key = ""
    current_lines: List[str] = []

    for raw_line in block_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if raw_line[:1].isspace() and current_key:
            current_lines.append(line.strip())
            continue
        if line.lstrip().startswith("- "):
            if current_key:
                current_lines.append(line.strip())
            continue
        key_match = re.match(r"^([A-Za-z0-9_ /()+&.-]+):\s*(.*)$", line)
        if key_match:
            if current_key:
                fields[current_key] = "\n".join(current_lines).strip()
            current_key = _normalize_key(key_match.group(1))
            current_lines = [key_match.group(2).strip()]
            continue
        if current_key:
            current_lines.append(line.strip())

    if current_key:
        fields[current_key] = "\n".join(current_lines).strip()
    return fields


def _parse_tags(raw_tags: str) -> List[str]:
    if not raw_tags:
        return []
    return normalize_tags([part.strip() for part in raw_tags.split(",") if part.strip()])


def _parse_structured_list(raw_value: str) -> List[Dict[str, Any]]:
    if not raw_value.strip():
        return []

    lines = [line.strip() for line in raw_value.splitlines() if line.strip()]
    items: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    pending_list_key = ""

    for line in lines:
        if line.startswith("- "):
            rest = line[2:].strip()
            if current is not None and pending_list_key and ":" not in rest:
                current.setdefault(pending_list_key, []).append(rest)
                continue

            if current is not None:
                items.append(current)
                current = None
                pending_list_key = ""

            if ":" in rest:
                key, value = rest.split(":", 1)
                normalized_key = _normalize_key(key)
                cleaned_value = value.strip()
                current = {normalized_key: cleaned_value if cleaned_value else []}
                pending_list_key = normalized_key if not cleaned_value else ""
            else:
                items.append({"value": rest})
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            normalized_key = _normalize_key(key)
            cleaned_value = value.strip()
            if current is None:
                current = {}
            if cleaned_value:
                current[normalized_key] = cleaned_value
                pending_list_key = ""
            else:
                current[normalized_key] = []
                pending_list_key = normalized_key
            continue

        if current is not None and pending_list_key:
            current.setdefault(pending_list_key, []).append(line)
        elif current is not None:
            current["detail"] = f"{current.get('detail', '')} {line}".strip()

    if current is not None:
        items.append(current)

    return items


def _render_section_body(fields: Dict[str, str]) -> str:
    rendered: List[str] = []
    ordered_keys = [
        "summary",
        "document_summary",
        "timeline_interpretation",
        "timeline_summary",
        "timeline_note",
        "plan_entry_point",
        "phase_role",
        "parent_phase",
        "questions",
        "plans",
        "timeline_groups",
        "stages",
        "workflow_scope",
        "workflow_components",
        "workflow_steps",
        "step_name",
        "step",
        "previous_step",
        "next_step",
        "service_components",
        "configuration_options",
        "platform_assets",
        "capability_stages",
        "advantage_categories",
        "company_claims",
        "user_value_points",
        "value_points",
        "engagement_options",
        "supported_stages",
        "benchmarks",
        "publications",
        "related_entities",
        "reference_label",
        "detail",
        "metrics",
    ]
    seen = set()
    for key in ordered_keys:
        value = fields.get(key, "").strip()
        if not value:
            continue
        seen.add(key)
        rendered.append(f"{key.replace('_', ' ').title()}: {value}")

    for key, value in fields.items():
        if key in seen or key in _METADATA_FIELDS or key in _RAW_STRUCTURED_FIELDS:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        rendered.append(f"{key.replace('_', ' ').title()}: {cleaned}")
    return "\n".join(rendered).strip()


def _base_section_metadata(document_fields: Dict[str, str], section_fields: Dict[str, str], title: str, order: int, path: Path) -> Dict[str, Any]:
    section_type = section_fields.get("section_type", "")
    metadata = {
        "prechunked": True,
        "source_format": "service_page_txt",
        "chunk_label": title,
        "structural_order": order,
        "section_title": title,
        "page_title": section_fields.get("page_title") or document_fields.get("page_title", ""),
        "service_name": section_fields.get("service_name") or document_fields.get("service_name", ""),
        "service_line": section_fields.get("service_line") or document_fields.get("service_line", ""),
        "source_url": section_fields.get("source_url") or document_fields.get("source_url", ""),
        "subcategory": section_fields.get("subcategory") or document_fields.get("subcategory", ""),
        "chunk_level": "subchunk" if section_type in EXPLICIT_SUBCHUNK_SECTION_TYPES else "section",
        "parent_section_ref": f"{path}:{order}:{title}",
    }
    if section_type in EXPLICIT_SUBCHUNK_SECTION_TYPES:
        metadata["subchunk_type"] = section_type
    for key in (
        "parent_section",
        "parent_section_type",
        "plan_name",
        "phase_name",
        "phase_role",
        "parent_phase",
        "milestone_name",
        "week_range",
        "step_name",
        "step",
        "previous_step",
        "next_step",
        "duration_weeks",
        "optional",
        "price_usd",
        "price_usd_min",
        "price_usd_max",
        "price_note",
        "pricing_tier",
        "unit",
        "unit_price_usd",
        "setup_fee_usd",
        "stage_type",
    ):
        if section_fields.get(key):
            metadata[key] = section_fields[key]
    if section_fields.get("retrieval_priority"):
        metadata["retrieval_priority"] = section_fields["retrieval_priority"]
    if section_fields.get("evidence_level"):
        metadata["evidence_level"] = section_fields["evidence_level"]
    if section_fields.get("topic_group"):
        metadata["topic_group"] = section_fields["topic_group"]
    if section_fields.get("relation_type"):
        metadata["relation_type"] = section_fields["relation_type"]
    return metadata


def _build_document(
    *,
    path: Path,
    title: str,
    body: str,
    section_type: str,
    tags: List[str],
    document_fields: Dict[str, str],
    section_fields: Dict[str, str],
    chunk_index: int,
    structural_tag: str,
    extra_metadata: Dict[str, Any] | None = None,
) -> Document:
    section = IngestionSection(
        company=section_fields.get("company") or document_fields.get("company") or "ProMab",
        title=title,
        body=body,
        section_type=section_type or "service_section",
        tags=tags,
        source_path=str(path),
        business_line=section_fields.get("business_line") or document_fields.get("business_line", ""),
        entity_type=section_fields.get("entity_type") or document_fields.get("entity_type", "service"),
        entity_name=section_fields.get("service_name") or document_fields.get("service_name", ""),
        document_type=section_fields.get("document_type") or document_fields.get("document_type", "service_page"),
        structural_tag=structural_tag,
    )
    metadata = build_chunk_metadata(section, chunk_index=chunk_index)
    metadata.update(extra_metadata or {})
    return Document(page_content=build_embedding_string(section), metadata=metadata)


def _build_pricing_subchunks(
    *,
    path: Path,
    document_fields: Dict[str, str],
    section_fields: Dict[str, str],
    section_title: str,
    section_order: int,
    next_index: int,
) -> List[Document]:
    docs: List[Document] = []
    section_tags = _parse_tags(section_fields.get("tags") or document_fields.get("tags", ""))
    common_metadata = _base_section_metadata(document_fields, section_fields, section_title, section_order, path)

    for plan in _parse_structured_list(section_fields.get("plans", "")):
        plan_name = _stringify(plan.get("plan_name"))
        if not plan_name:
            continue
        body_lines = [
            f"Plan name: {plan_name}",
            f"Plan summary: {_stringify(plan.get('plan_summary'))}",
            f"Timeline summary: {_stringify(plan.get('timeline_summary'))}",
            f"Total duration weeks: {_stringify(plan.get('total_duration_weeks'))}",
        ]
        body = "\n".join(line for line in body_lines if not line.endswith(":"))
        docs.append(
            _build_document(
                path=path,
                title=f"{section_title} - {plan_name}",
                body=body,
                section_type=section_fields.get("section_type") or "pricing_overview",
                tags=normalize_tags([*section_tags, plan_name, "plan summary"]),
                document_fields=document_fields,
                section_fields=section_fields,
                chunk_index=next_index,
                structural_tag="pricing_plan_subchunk",
                extra_metadata={
                    **common_metadata,
                    "chunk_level": "subchunk",
                    "subchunk_type": "plan_summary",
                    "plan_name": plan_name,
                    "parent_section_type": section_fields.get("section_type", ""),
                    "chunk_label": f"{section_title} - {plan_name}",
                },
            )
        )
        next_index += 1

    return docs


def _build_service_plan_subchunks(
    *,
    path: Path,
    document_fields: Dict[str, str],
    section_fields: Dict[str, str],
    section_title: str,
    section_order: int,
    next_index: int,
) -> List[Document]:
    docs: List[Document] = []
    section_tags = _parse_tags(section_fields.get("tags") or document_fields.get("tags", ""))
    common_metadata = _base_section_metadata(document_fields, section_fields, section_title, section_order, path)

    for group in _parse_structured_list(section_fields.get("timeline_groups", "")):
        group_name = _stringify(group.get("group_name"))
        if not group_name:
            continue
        body_lines = [
            f"Plan name: {section_title}",
            f"Timeline group: {group_name}",
            f"Total duration weeks: {_stringify(group.get('total_duration_weeks'))}",
            f"Phases: {_stringify(group.get('phases'))}",
        ]
        docs.append(
            _build_document(
                path=path,
                title=f"{section_title} - {group_name}",
                body="\n".join(line for line in body_lines if not line.endswith(":")),
                section_type=section_fields.get("section_type") or "service_plan",
                tags=normalize_tags([*section_tags, group_name, "timeline group"]),
                document_fields=document_fields,
                section_fields=section_fields,
                chunk_index=next_index,
                structural_tag="timeline_group_subchunk",
                extra_metadata={
                    **common_metadata,
                    "chunk_level": "subchunk",
                    "subchunk_type": "timeline_group",
                    "plan_name": section_title,
                    "timeline_group_name": group_name,
                    "parent_section_type": section_fields.get("section_type", ""),
                    "chunk_label": f"{section_title} - {group_name}",
                },
            )
        )
        next_index += 1

    for stage in _parse_structured_list(section_fields.get("stages", "")):
        phase_name = _stringify(stage.get("phase"))
        if not phase_name:
            continue
        body_lines = [
            f"Plan name: {section_title}",
            f"Phase: {phase_name}",
            f"Stage type: {_stringify(stage.get('stage_type'))}",
            f"Duration weeks: {_stringify(stage.get('duration_weeks'))}",
            f"Description: {_stringify(stage.get('description'))}",
            f"Price USD: {_stringify(stage.get('price_usd'))}",
            f"Price USD Min: {_stringify(stage.get('price_usd_min'))}",
            f"Price USD Max: {_stringify(stage.get('price_usd_max'))}",
            f"Price note: {_stringify(stage.get('price_note'))}",
            f"Optional: {_stringify(stage.get('optional'))}",
        ]
        docs.append(
            _build_document(
                path=path,
                title=f"{section_title} - {phase_name}",
                body="\n".join(line for line in body_lines if not line.endswith(":")),
                section_type=section_fields.get("section_type") or "service_plan",
                tags=normalize_tags([*section_tags, section_title, phase_name, _stringify(stage.get("stage_type")), "phase"]),
                document_fields=document_fields,
                section_fields=section_fields,
                chunk_index=next_index,
                structural_tag="phase_subchunk",
                extra_metadata={
                    **common_metadata,
                    "chunk_level": "subchunk",
                    "subchunk_type": "phase",
                    "plan_name": section_title,
                    "phase_name": phase_name,
                    "stage_type": _stringify(stage.get("stage_type")),
                    "duration_weeks": _stringify(stage.get("duration_weeks")),
                    "optional": _stringify(stage.get("optional")),
                    "parent_section_type": section_fields.get("section_type", ""),
                    "chunk_label": f"{section_title} - {phase_name}",
                },
            )
        )
        next_index += 1

    return docs


def _build_workflow_subchunks(
    *,
    path: Path,
    document_fields: Dict[str, str],
    section_fields: Dict[str, str],
    section_title: str,
    section_order: int,
    next_index: int,
) -> List[Document]:
    docs: List[Document] = []
    section_tags = _parse_tags(section_fields.get("tags") or document_fields.get("tags", ""))
    common_metadata = _base_section_metadata(document_fields, section_fields, section_title, section_order, path)

    for component in _parse_structured_list(section_fields.get("workflow_components", "")):
        step_name = _stringify(component.get("name"))
        if not step_name:
            continue
        step_no = _stringify(component.get("step"))
        body_lines = [
            f"Workflow section: {section_title}",
            f"Step: {step_no}",
            f"Component: {step_name}",
            f"Stage type: {_stringify(component.get('stage_type'))}",
            f"Description: {_stringify(component.get('description'))}",
        ]
        docs.append(
            _build_document(
                path=path,
                title=f"{section_title} - {step_name}",
                body="\n".join(line for line in body_lines if not line.endswith(":")),
                section_type=section_fields.get("section_type") or "workflow_highlights",
                tags=normalize_tags([*section_tags, step_name, _stringify(component.get("stage_type")), "workflow step"]),
                document_fields=document_fields,
                section_fields=section_fields,
                chunk_index=next_index,
                structural_tag="workflow_step_subchunk",
                extra_metadata={
                    **common_metadata,
                    "chunk_level": "subchunk",
                    "subchunk_type": "workflow_step",
                    "workflow_step_name": step_name,
                    "workflow_step": step_no,
                    "stage_type": _stringify(component.get("stage_type")),
                    "parent_section_type": section_fields.get("section_type", ""),
                    "chunk_label": f"{section_title} - {step_name}",
                },
            )
        )
        next_index += 1

    return docs


def _build_subchunks(
    *,
    path: Path,
    document_fields: Dict[str, str],
    section_fields: Dict[str, str],
    section_title: str,
    section_order: int,
    next_index: int,
) -> List[Document]:
    section_type = section_fields.get("section_type", "")
    if section_type == "pricing_overview":
        return _build_pricing_subchunks(
            path=path,
            document_fields=document_fields,
            section_fields=section_fields,
            section_title=section_title,
            section_order=section_order,
            next_index=next_index,
        )
    if section_type == "service_plan":
        return _build_service_plan_subchunks(
            path=path,
            document_fields=document_fields,
            section_fields=section_fields,
            section_title=section_title,
            section_order=section_order,
            next_index=next_index,
        )
    if section_type == "workflow_highlights":
        return _build_workflow_subchunks(
            path=path,
            document_fields=document_fields,
            section_fields=section_fields,
            section_title=section_title,
            section_order=section_order,
            next_index=next_index,
        )
    return []


def parse_service_page_file(path: Path) -> List[Document]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    document_match = DOCUMENT_PATTERN.search(text)
    document_fields = _parse_key_values(document_match.group(1)) if document_match else {}
    documents: List[Document] = []

    for section_order, match in enumerate(SECTION_PATTERN.finditer(text)):
        section_fields = _parse_key_values(match.group(1))
        title = (
            section_fields.get("section_title")
            or section_fields.get("title")
            or section_fields.get("section_type")
            or f"section_{section_order}"
        )
        body = _render_section_body({**document_fields, **section_fields})
        section_doc = _build_document(
            path=path,
            title=title,
            body=body,
            section_type=section_fields.get("section_type") or "service_section",
            tags=_parse_tags(section_fields.get("tags") or document_fields.get("tags", "")),
            document_fields=document_fields,
            section_fields=section_fields,
            chunk_index=len(documents),
            structural_tag="section",
            extra_metadata=_base_section_metadata(document_fields, section_fields, title, section_order, path),
        )
        documents.append(section_doc)

        subchunks = _build_subchunks(
            path=path,
            document_fields=document_fields,
            section_fields=section_fields,
            section_title=title,
            section_order=section_order,
            next_index=len(documents),
        )
        documents.extend(subchunks)

    return documents


def iter_service_page_files() -> Iterable[Path]:
    files: List[Path] = []
    for source_dir in SERVICE_PAGE_SOURCE_DIRS:
        if not source_dir.exists():
            continue
        files.extend(
            path
            for path in source_dir.glob("*.txt")
            if path.is_file() and SERVICE_PAGE_FILE_PATTERN.search(path.name)
        )
    return sorted(files)


def load_service_page_documents() -> List[Document]:
    docs: List[Document] = []
    for path in iter_service_page_files():
        docs.extend(parse_service_page_file(path))
    return docs


__all__ = [
    "SERVICE_PAGE_SOURCE_DIR",
    "SERVICE_PAGE_SOURCE_DIRS",
    "iter_service_page_files",
    "load_service_page_documents",
    "parse_service_page_file",
]
