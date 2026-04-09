from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
PRODUCT_DATA_FILES = {
    "antibody": BASE_DIR / "data" / "processed" / "antibody_products.xlsx",
    "car_t": BASE_DIR / "data" / "processed" / "CAR_T_products.xlsx",
    "mrna_lnp": BASE_DIR / "data" / "processed" / "mRNA_LNP_products.xlsx",
}


@dataclass(frozen=True)
class ProductRegistryEntry:
    catalog_no: str
    canonical_name: str
    business_line: str
    aliases: tuple[str, ...] = ()
    target_antigen: str = ""
    application_text: str = ""
    species_reactivity_text: str = ""
    source_file: str = ""
    source_sheet: str = ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = " ".join(str(value or "").strip().split())
    return text


def _normalize_text(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("×", "x")
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\b6\s*x?\s*his\b", "6xhis", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _split_aliases(value: Any) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []

    aliases: list[str] = []
    seen: set[str] = set()
    for raw in text.replace(";", ",").split(","):
        alias = _clean_text(raw)
        normalized = _normalize_text(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(alias)
    return aliases


def _dedupe_aliases(values: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = _clean_text(value)
        normalized = _normalize_text(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(alias)
    return tuple(deduped)


def _expand_mrna_lnp_aliases(values: list[str]) -> list[str]:
    expanded: list[str] = list(values)
    for value in values:
        alias = _clean_text(value)
        if not alias:
            continue
        lowered = alias.lower()
        if "mrna-lnp" in lowered:
            expanded.append(alias.replace("mRNA-LNP", "mRNA-Lipid Nanoparticle"))
            expanded.append(alias.replace("mrna-lnp", "mrna-lipid nanoparticle"))
        if "mrna lnp" in lowered:
            expanded.append(alias.replace("mRNA LNP", "mRNA Lipid Nanoparticle"))
            expanded.append(alias.replace("mrna lnp", "mrna lipid nanoparticle"))
    return expanded


def _extract_antibody_target_aliases(canonical_name: str) -> list[str]:
    cleaned = _clean_text(canonical_name)
    if " antibody to " not in cleaned.lower():
        return []

    target = re.split(r"(?i)\bantibody to\b", cleaned, maxsplit=1)[-1].strip()
    if not target:
        return []

    aliases = [target]
    stripped_variant = re.sub(r"\s*\([^)]*\)\s*$", "", target).strip()
    if stripped_variant and stripped_variant != target:
        aliases.append(stripped_variant)
    return aliases


def _expand_antibody_alias_variants(values: list[str]) -> list[str]:
    expanded: list[str] = list(values)
    for value in values:
        alias = _clean_text(value)
        if not alias:
            continue
        lowered = alias.lower().replace("×", "x")
        if "6 his" in lowered or "6xhis" in lowered:
            variant = re.sub(r"(?i)\b6\s*x?\s*his\b", "6xHis", alias.replace("×", "x"))
            expanded.append(variant)
            expanded.append(variant.replace("6xHis", "6×His"))
            expanded.append(variant.replace("6xHis", "6 His"))
    return expanded


def _build_antibody_entries() -> list[ProductRegistryEntry]:
    path = PRODUCT_DATA_FILES["antibody"]
    entries: list[ProductRegistryEntry] = []

    for sheet_name in ["Monoclonal Antibody", "Polyclonal Antibody"]:
        df = pd.read_excel(path, sheet_name=sheet_name)
        for _, raw in df.iterrows():
            catalog_no = _clean_text(raw.get("Catalog#"))
            canonical_name = _clean_text(raw.get("title"))
            if not catalog_no or not canonical_name:
                continue

            aliases = _dedupe_aliases(
                _expand_antibody_alias_variants(
                    [
                        canonical_name,
                        catalog_no,
                        *_extract_antibody_target_aliases(canonical_name),
                        *_split_aliases(raw.get("Also known as ")),
                    ]
                )
            )
            entries.append(
                ProductRegistryEntry(
                    catalog_no=catalog_no,
                    canonical_name=canonical_name,
                    business_line="antibody",
                    aliases=aliases,
                    target_antigen=_extract_antibody_target_aliases(canonical_name)[0] if _extract_antibody_target_aliases(canonical_name) else "",
                    application_text=_clean_text(raw.get("Applications")),
                    species_reactivity_text=_clean_text(raw.get("Species Reactivity")),
                    source_file=path.name,
                    source_sheet=sheet_name,
                )
            )

    return entries


def _generate_cart_name(raw: pd.Series) -> str:
    explicit_name = _clean_text(raw.get("name"))
    if explicit_name:
        return explicit_name

    target = _clean_text(raw.get("target_antigen"))
    domain = _clean_text(raw.get("costimulatory_domain"))
    parts = [part for part in [target, domain, "CAR-T"] if part]
    return " ".join(parts)


def _build_cart_entries() -> list[ProductRegistryEntry]:
    path = PRODUCT_DATA_FILES["car_t"]
    df = pd.read_excel(path, sheet_name="Sheet1")
    entries: list[ProductRegistryEntry] = []

    for _, raw in df.iterrows():
        catalog_no = _clean_text(raw.get("catalog_no"))
        canonical_name = _generate_cart_name(raw)
        if not catalog_no or not canonical_name:
            continue

        aliases = _dedupe_aliases(
            [
                canonical_name,
                catalog_no,
                _clean_text(raw.get("target_antigen")),
                _clean_text(raw.get("group_name")),
                _clean_text(raw.get("construct")),
            ]
        )
        entries.append(
            ProductRegistryEntry(
                catalog_no=catalog_no,
                canonical_name=canonical_name,
                business_line="car_t",
                aliases=aliases,
                target_antigen=_clean_text(raw.get("target_antigen")),
                application_text="",
                species_reactivity_text="",
                source_file=path.name,
                source_sheet="Sheet1",
            )
        )

    return entries


def _build_mrna_entries() -> list[ProductRegistryEntry]:
    path = PRODUCT_DATA_FILES["mrna_lnp"]
    df = pd.read_excel(path, sheet_name="Sheet1")
    entries: list[ProductRegistryEntry] = []

    for _, raw in df.iterrows():
        catalog_no = _clean_text(raw.get("catalog_no"))
        canonical_name = _clean_text(raw.get("name"))
        if not catalog_no or not canonical_name:
            continue

        aliases = _dedupe_aliases(
            _expand_mrna_lnp_aliases(
                [
                    canonical_name,
                    catalog_no,
                    _clean_text(raw.get("type")),
                    _clean_text(raw.get("format")),
                    "mRNA-Lipid Nanoparticle",
                ]
            )
        )
        entries.append(
            ProductRegistryEntry(
                catalog_no=catalog_no,
                canonical_name=canonical_name,
                business_line="mrna_lnp",
                aliases=aliases,
                target_antigen="",
                application_text=_clean_text(raw.get("format")),
                species_reactivity_text="",
                source_file=path.name,
                source_sheet="Sheet1",
            )
        )

    return entries


@lru_cache(maxsize=1)
def load_product_registry() -> tuple[ProductRegistryEntry, ...]:
    entries = [
        *_build_antibody_entries(),
        *_build_cart_entries(),
        *_build_mrna_entries(),
    ]
    return tuple(entries)


@lru_cache(maxsize=1)
def get_product_registry_payload() -> dict[str, Any]:
    entries = load_product_registry()

    by_catalog_no: dict[str, dict[str, Any]] = {}
    alias_to_catalog_nos: dict[str, list[str]] = {}

    for entry in entries:
        by_catalog_no[entry.catalog_no] = {
            "catalog_no": entry.catalog_no,
            "canonical_name": entry.canonical_name,
            "business_line": entry.business_line,
            "aliases": list(entry.aliases),
            "target_antigen": entry.target_antigen,
            "application_text": entry.application_text,
            "species_reactivity_text": entry.species_reactivity_text,
            "source_file": entry.source_file,
            "source_sheet": entry.source_sheet,
        }
        for alias in entry.aliases:
            normalized = _normalize_text(alias)
            if not normalized:
                continue
            catalog_nos = alias_to_catalog_nos.setdefault(normalized, [])
            if entry.catalog_no not in catalog_nos:
                catalog_nos.append(entry.catalog_no)

    return {
        "entries": list(by_catalog_no.values()),
        "by_catalog_no": by_catalog_no,
        "alias_to_catalog_nos": alias_to_catalog_nos,
    }


def lookup_products_by_alias(alias: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(alias)
    if not normalized:
        return []

    payload = get_product_registry_payload()
    catalog_nos = payload["alias_to_catalog_nos"].get(normalized, [])
    return [
        payload["by_catalog_no"][catalog_no]
        for catalog_no in catalog_nos
        if catalog_no in payload["by_catalog_no"]
    ]


def lookup_product_by_catalog_no(catalog_no: str) -> dict[str, Any] | None:
    normalized = _clean_text(catalog_no)
    if not normalized:
        return None
    return get_product_registry_payload()["by_catalog_no"].get(normalized)


def canonicalize_product_name(value: str) -> str:
    cleaned = _clean_text(value)
    matches = lookup_products_by_alias(cleaned)
    if len(matches) == 1:
        canonical_name = _clean_text(matches[0].get("canonical_name"))
        if canonical_name:
            return canonical_name
    return cleaned


__all__ = [
    "ProductRegistryEntry",
    "PRODUCT_DATA_FILES",
    "canonicalize_product_name",
    "get_product_registry_payload",
    "load_product_registry",
    "lookup_product_by_catalog_no",
    "lookup_products_by_alias",
]
