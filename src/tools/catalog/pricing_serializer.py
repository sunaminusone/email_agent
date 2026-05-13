"""Pricing record → LLM-ready dict.

Phase 3 of the responder refactor. Pricing has two record shapes that
travel through the same tool:

  * PG pricing records (from ``_pricing_record`` in pricing_tool.py):
    catalog product summary — already clean, just drop empty fields.

  * Service-flyer pricing records (from
    ``src.rag.flyer_pricing._build_flyer_pricing_record``): represent a
    plan or one phase of a multi-phase plan, sourced from Chroma flyer
    chunks. ``optional`` is a raw "yes"/"" string sentinel that becomes
    ``is_optional: bool``; the ambiguous bare ``price`` is renamed to
    ``phase_price`` when ``phase_name`` is set so the LLM doesn't
    mistake it for a plan total.

The DRAFTING nuance — "don't sum phase prices, cite plan_total_price
directly, optional phases price only if included" — is NOT in the
serializer (it's a USE policy, not a SHAPE rule). It lives in
``src/responser/csr/prompts/pricing_semantics.md`` and is conditionally
loaded into the draft system prompt when pricing_lookup_tool fired.

Contract: ``docs/RESPONDER_DESIGN_V4.md`` ⭐ section.
"""
from __future__ import annotations

from typing import Any


_OPTIONAL_TRUE_LITERALS = frozenset({"yes", "true", "1", "y"})


def _is_present(value: Any) -> bool:
    """True iff the value should appear in the llm view.

    Keep ``0`` (legitimate price/quantity) and ``False`` (booleans like
    is_optional). Drop None and empty strings.
    """
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def serialize_pg_pricing_record(raw: dict[str, Any]) -> dict[str, Any]:
    """PG pricing record — already concise, just drop empty fields."""
    out: dict[str, Any] = {}
    for key in (
        "catalog_no",
        "name",
        "price",
        "currency",
        "lead_time_text",
        "business_line",
    ):
        value = raw.get(key)
        if _is_present(value):
            out[key] = value
    return out


def serialize_flyer_pricing_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Service-flyer pricing record (Chroma chunk-derived).

    Field-name fixes:
      * ``optional: "yes" / ""`` → ``is_optional: True`` (drop when False)
      * Bare ``price`` → ``phase_price`` when ``phase_name`` is set (so
        LLM can't mistake it for a plan total)

    All other fields pass through unchanged; the drafting fragment teaches
    the LLM HOW to use them (don't sum phases, cite plan_total_price etc.).
    """
    out: dict[str, Any] = {"_subsource": "service_flyer"}

    for key in (
        "service_name",
        "business_line",
        "plan_name",
        "phase_name",
        "phase_role",
        "duration_weeks",
        "plan_total_price",
        "price_min",
        "price_max",
        "currency",
        "pricing_tier",
        "unit",
        "unit_price",
        "setup_fee",
        "price_note",
        "source_section",
        "source_excerpt",
    ):
        value = raw.get(key)
        if _is_present(value):
            out[key] = value

    # `price` semantic depends on phase context — rename when this row
    # represents a single phase of a multi-phase plan.
    price = raw.get("price")
    if _is_present(price):
        phase_name = raw.get("phase_name") or ""
        if str(phase_name).strip():
            out["phase_price"] = price
        else:
            out["price"] = price

    # `optional` sentinel → bool. Only surface when True (avoids noise on
    # the common is_optional=False case).
    optional_raw = str(raw.get("optional", "")).strip().lower()
    if optional_raw in _OPTIONAL_TRUE_LITERALS:
        out["is_optional"] = True

    return out


def serialize_pricing_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Entry point — dispatch on ``_subsource``."""
    if raw.get("_subsource") == "service_flyer":
        return serialize_flyer_pricing_record(raw)
    return serialize_pg_pricing_record(raw)


__all__ = [
    "serialize_pricing_record",
    "serialize_pg_pricing_record",
    "serialize_flyer_pricing_record",
]
