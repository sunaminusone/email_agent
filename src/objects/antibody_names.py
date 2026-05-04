"""Extract canonical gene/protein symbols from antibody product names.

Used by:
  * scripts/import_antibody_from_jsonl.py — populate target_antigen and
    seed aliases on first ingestion.
  * scripts/backfill_antibody_target_aliases.py — retrofit the same
    fields on already-imported rows.

Coverage on current 3534 antibody rows: 100% (no unmatched names).
Pattern breakdown:
  * 79% "X Primary Antibody"  — e.g. "SDHA Primary Antibody" → SDHA
  * 13% "X (PT...) PT® Rabbit mAb" — e.g. "TFEB (PT0684R) PT® Rabbit mAb" → TFEB
  *  8% "Host Type Antibody to X" — e.g. "Mouse Monoclonal Antibody to CD300F" → CD300F

When the title carries a species qualifier ("human IgG", "Mouse TUG"),
the stripped form is preferred as the canonical symbol but the
un-stripped form is also returned so customer queries match either way.
"""
from __future__ import annotations

import re


_SPECIES_PREFIX = re.compile(
    r"^(?:Mouse|Rat|Rabbit|Human|human|Pig|Cow|Bovine|Sheep|Chicken|Donkey|Hamster|Goat)\s+",
)
_HOST_TYPE_TO_X = re.compile(
    r"^(?:Mouse|Rabbit|Rat|Goat|Sheep|Chicken|Donkey|Hamster|Host)\s+"
    r"(?:Monoclonal|Polyclonal)\s+[Aa]ntibody\s+to\s+(.+)$",
    re.IGNORECASE,
)
_ANTI_DASH = re.compile(r"^[Aa]nti[-\s]+(.+)$")
_X_PRIMARY = re.compile(r"^(.+?)\s+[Pp]rimary [Aa]ntibody$")
_PT_BRAND = re.compile(r"^(.+?)\s*\(.+\bmAb\b")


def extract_canonical_symbols(name: str) -> list[str]:
    """Return canonical-symbol candidates from an antibody product name.

    The first element is the best-effort canonical symbol intended for
    target_antigen; additional elements are alternative forms (e.g. the
    species-prefix-included variant) to register as extra aliases.
    """
    s = (name or "").strip()
    if not s:
        return []

    m = _HOST_TYPE_TO_X.match(s)
    if m:
        return [m.group(1).strip()]

    m = _ANTI_DASH.match(s)
    if m:
        return [m.group(1).strip()]

    m = _X_PRIMARY.match(s)
    if m:
        x = m.group(1).strip()
        stripped = _SPECIES_PREFIX.sub("", x)
        if stripped and stripped != x:
            return [stripped, x]
        return [x]

    m = _PT_BRAND.match(s)
    if m:
        return [m.group(1).strip()]

    return []
