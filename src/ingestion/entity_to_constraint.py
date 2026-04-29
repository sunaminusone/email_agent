"""Bridge: parser-extracted attribute entities → AttributeConstraint.

The parser extracts free-form entity spans for attribute dimensions
(isotype, costim_domain, CAR-T group_name).  This module normalizes
those spans against fixed whitelists and converts them into
AttributeConstraints that downstream constraint_matching can apply.

Whitelists defend against LLM hallucination — only values that match
the controlled vocabulary become constraints.  Anything else is
silently dropped.
"""
from __future__ import annotations

import re

from src.ingestion.models import (
    AttributeConstraint,
    EntitySpan,
    ParserEntitySignals,
    SourceAttribution,
)


_ISOTYPE_HEAVY_RE = re.compile(r"\big\s*(g[1-4][a-c]?|g|m|a|d|e)\b", re.IGNORECASE)
_ISOTYPE_LIGHT_RE = re.compile(r"(kappa|lambda)", re.IGNORECASE)
_SPECIES_PREFIXES: tuple[str, ...] = ("mouse ", "rat ", "rabbit ", "human ", "hamster ", "goat ")

_COSTIM_ALIASES: dict[str, str] = {
    "cd28": "CD28",
    "41bb": "4-1BB",
    "4-1bb": "4-1BB",
    "cd28+4-1bb": "CD28+4-1BB",
    "cd28-4-1bb": "CD28+4-1BB",
    "gitr": "GITR",
}

_CAR_T_GROUP_ALIASES: dict[str, str] = {
    "car-t cells": "CAR-T Cells",
    "car-t cell": "CAR-T Cells",
    "car t cells": "CAR-T Cells",
    "car t cell": "CAR-T Cells",
    "cart cells": "CAR-T Cells",
    "engineered car-t target cells": "Engineered CAR-T Target Cells",
    "engineered car t target cells": "Engineered CAR-T Target Cells",
    "engineered target cells": "Engineered CAR-T Target Cells",
    "target cells": "Engineered CAR-T Target Cells",
    "non-transduced t cells": "Non-Transduced T Cells",
    "non transduced t cells": "Non-Transduced T Cells",
    "untransduced t cells": "Non-Transduced T Cells",
    "car detection probes": "CAR Detection Probes",
    "car detection probe": "CAR Detection Probes",
    "detection probes": "CAR Detection Probes",
    "cell media and activation beads": "Cell Media and Activation Beads",
    "activation beads": "Cell Media and Activation Beads",
    "cell media": "Cell Media and Activation Beads",
    "non-transduced macrophages": "Non-Transduced Macrophages",
    "non transduced macrophages": "Non-Transduced Macrophages",
    "untransduced macrophages": "Non-Transduced Macrophages",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _normalize_isotype(raw: str) -> str:
    text = _clean(raw)
    if not text:
        return ""
    text = text.replace("κ", "kappa").replace("λ", "lambda")
    for prefix in _SPECIES_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    heavy_match = _ISOTYPE_HEAVY_RE.search(text)
    if not heavy_match:
        return ""
    heavy_suffix = re.sub(r"\s+", "", heavy_match.group(1)).lower()
    if heavy_suffix.startswith("g"):
        heavy = "IgG" + heavy_suffix[1:]
    else:
        heavy = "Ig" + heavy_suffix.upper()
    light_match = _ISOTYPE_LIGHT_RE.search(text)
    if light_match:
        return f"{heavy}/{light_match.group(1).lower()}"
    return heavy


def _normalize_costim(raw: str) -> str:
    text = _clean(raw)
    if not text:
        return ""
    text = re.sub(
        r"^(with|using|the|costim(ulatory)?(\s+domain)?|domain|signaling)\s+",
        "",
        text,
    )
    text = text.replace("/", "+").replace("&", "+").replace(" and ", "+")
    text = re.sub(r"\s*\+\s*", "+", text)
    text = re.sub(r"4\s+1bb", "4-1bb", text)
    text = text.strip()
    return _COSTIM_ALIASES.get(text, "")


def _normalize_car_t_group(raw: str) -> str:
    text = _clean(raw)
    if not text:
        return ""
    return _CAR_T_GROUP_ALIASES.get(text, "")


def _build_constraint(attribute: str, canonical_value: str, span: EntitySpan) -> AttributeConstraint:
    return AttributeConstraint(
        attribute=attribute,
        operator="equals",
        value=canonical_value,
        raw=span.text or span.raw,
        attribution=SourceAttribution(
            source_type="parser",
            recency="CURRENT_TURN",
            source_label="parser_entity_bridge",
        ),
    )


def entities_to_attribute_constraints(entities: ParserEntitySignals) -> list[AttributeConstraint]:
    """Convert whitelisted parser entity spans into AttributeConstraints."""
    out: list[AttributeConstraint] = []
    seen: set[tuple[str, str]] = set()

    def _emit(attribute: str, canonical_value: str, span: EntitySpan) -> None:
        if not canonical_value:
            return
        key = (attribute, canonical_value)
        if key in seen:
            return
        seen.add(key)
        out.append(_build_constraint(attribute, canonical_value, span))

    for span in entities.isotypes:
        _emit("isotype", _normalize_isotype(span.text or span.raw), span)
    for span in entities.costim_domains:
        _emit("costim_domain", _normalize_costim(span.text or span.raw), span)
    for span in entities.car_t_groups:
        _emit("car_t_group", _normalize_car_t_group(span.text or span.raw), span)
    return out
