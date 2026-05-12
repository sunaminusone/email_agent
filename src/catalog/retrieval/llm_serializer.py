"""Catalog record → LLM-ready dict.

Phase 1 step 4 of the responder refactor. Tool-side serializer that
projects ``serialize_match`` output into a shape the drafter LLM can
consume directly, without needing per-tool schema knowledge in its
system prompt.

Contract: ``docs/RESPONDER_DESIGN_V4.md`` ⭐ section.

What this serializer does:
  * Drops cross-facet None fields (an antibody record's LEFT-JOINed CAR-T
    columns etc. are filled with None — they pollute the LLM view).
  * Drops internal scoring fields (``score``, ``match_rank``,
    ``matched_field``, ``matched_value``, ``id``).
  * Resolves sentinel values (``sequence: "full" / "N" / ""`` → omit,
    treat as missing). Companion of ``_materialize_missing_answerable_fields``
    in ``extractors.py`` which handles ``price`` / ``lead_time_text``.
  * Preserves field names from the raw schema (``wb_dilution`` is clear
    enough — verbose like ``recommended_dilution_western_blot`` doesn't
    actually help the LLM and bloats prompts).

What this serializer does NOT do:
  * Rephrase content (immunogen / references_text — leave verbatim;
    the drafter prompt covers "preserve as cited").
  * HTML stripping (references_text may carry ``<br />`` etc.; drafter
    prompt's "extract citation text, don't paste raw tags" rule covers it).
  * Wrap None price fields in ``(not on file)`` sentinel — that's the
    extractor's job via ``_materialize_missing_answerable_fields``.
"""
from __future__ import annotations

from typing import Any


# Sequence values that mean "no public sequence on file" (per
# draft_llm.py:117-119 convention). Comparing case-insensitively.
_SEQUENCE_SENTINELS = frozenset({"full", "n", ""})


# Fields shared across every business line. Kept in stable order so the
# llm view reads consistently.
_COMMON_FIELDS: tuple[str, ...] = (
    "catalog_no",
    "name",
    "display_name",
    "business_line",
    "record_type",
    "target_antigen",
    "price",
    "price_text",
    "lead_time_text",
    "currency",
    "size",
    "format",
    "also_known_as",
    "application_text",
    "species_reactivity_text",
    "formulation",
    "shipping",
    "storage",
    "description",
)

_ANTIBODY_FIELDS: tuple[str, ...] = (
    "host",
    "isotype",
    "clone",
    "molecular_weight",
    "gene_id",
    "wb_dilution",
    "elisa_dilution",
    "ihc_dilution",
    "icc_dilution",
    "fcm_dilution",
    "immunogen",
    "sequence",
    "references_text",
)

_CART_FIELDS: tuple[str, ...] = (
    "construct",
    "costimulatory_domain",
    "group_name",
    "group_type",
    "group_subtype",
    "group_summary",
    "cell_number",
    "marker",
    "unit",
)

_LNP_FIELDS: tuple[str, ...] = (
    "lnp_type",
    "lnp_application",
    "application_handling",
    "cell_type_tested",
    "data_sheet_url",
)


def _normalize_sequence(value: Any) -> Any:
    """Return value if it's a real sequence string, else None to signal
    'omit from llm view'."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _SEQUENCE_SENTINELS:
        return None
    return value


def _select_fields(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fields:
        value = record.get(field)
        if field == "sequence":
            value = _normalize_sequence(value)
        if value is None or value == "":
            continue
        out[field] = value
    return out


def serialize_antibody_record(record: dict[str, Any]) -> dict[str, Any]:
    return _select_fields(record, _COMMON_FIELDS + _ANTIBODY_FIELDS)


def serialize_cart_record(record: dict[str, Any]) -> dict[str, Any]:
    return _select_fields(record, _COMMON_FIELDS + _CART_FIELDS)


def serialize_lnp_record(record: dict[str, Any]) -> dict[str, Any]:
    return _select_fields(record, _COMMON_FIELDS + _LNP_FIELDS)


def serialize_catalog_record(record: dict[str, Any]) -> dict[str, Any]:
    """Entry point — dispatch by business_line.

    Unknown / "Other Products" → keep common fields only. Caller (product_tool)
    invokes this on every catalog match before emitting ``llm_records``.
    """
    business_line = (record.get("business_line") or "").strip()
    if business_line == "Antibody":
        return serialize_antibody_record(record)
    if business_line in ("CAR-T/CAR-NK", "CAR-T"):
        return serialize_cart_record(record)
    if business_line == "mRNA-LNP":
        return serialize_lnp_record(record)
    # "Other Products" / unknown — only the common fields apply.
    return _select_fields(record, _COMMON_FIELDS)


__all__ = [
    "serialize_catalog_record",
    "serialize_antibody_record",
    "serialize_cart_record",
    "serialize_lnp_record",
]
