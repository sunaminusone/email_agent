from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import psycopg

from src.objects.normalizers import clean_text, dedupe_preserve_order, normalize_object_alias


BASE_DIR = Path(__file__).resolve().parents[3]
PRODUCT_DATA_FILES = {
    "antibody": BASE_DIR / "data" / "processed" / "antibody_products.xlsx",
    "car_t": BASE_DIR / "data" / "processed" / "CAR_T_products.xlsx",
    "mrna_lnp": BASE_DIR / "data" / "processed" / "mRNA_LNP_products.xlsx",
}
PRODUCT_REGISTRY_BACKEND = (os.getenv("OBJECTS_PRODUCT_REGISTRY_BACKEND") or "excel").strip().lower()
PRODUCT_REGISTRY_TABLE = os.getenv("OBJECTS_PRODUCT_REGISTRY_TABLE", "product_registry")


@dataclass(frozen=True)
class ProductRegistryEntry:
    catalog_no: str
    canonical_name: str
    business_line: str
    aliases: tuple[str, ...] = ()
    target_antigen: str = ""
    application_text: str = ""
    species_reactivity_text: str = ""
    format_or_size: str = ""
    clone: str = ""
    clonality: str = ""
    isotype: str = ""
    ig_class: str = ""
    gene_id: str = ""
    gene_accession: str = ""
    swissprot: str = ""
    costimulatory_domain: str = ""
    construct: str = ""
    product_type: str = ""
    group_name: str = ""
    group_type: str = ""
    group_subtype: str = ""
    group_summary: str = ""
    price_usd: str = ""
    unit: str = ""
    cell_number: str = ""
    marker: str = ""
    source_file: str = ""
    source_sheet: str = ""


@dataclass(frozen=True)
class ProductAliasRecord:
    value: str
    alias_kind: str


class ProductRegistrySource(Protocol):
    def load_entries(self) -> tuple[ProductRegistryEntry, ...]:
        ...


class ExcelProductRegistrySource:
    def __init__(self, data_files: dict[str, Path] | None = None) -> None:
        self._data_files = data_files or PRODUCT_DATA_FILES

    def load_entries(self) -> tuple[ProductRegistryEntry, ...]:
        return tuple(
            [
                *self._build_antibody_entries(),
                *self._build_cart_entries(),
                *self._build_mrna_entries(),
            ]
        )

    def _build_antibody_entries(self) -> list[ProductRegistryEntry]:
        path = self._data_files["antibody"]
        entries: list[ProductRegistryEntry] = []

        for sheet_name in ["Monoclonal Antibody", "Polyclonal Antibody"]:
            df = pd.read_excel(path, sheet_name=sheet_name)
            for _, raw in df.iterrows():
                catalog_no = _safe_text(raw.get("Catalog#"))
                canonical_name = _safe_text(raw.get("title"))
                if not catalog_no or not canonical_name:
                    continue

                application_text = _safe_text(raw.get("Applications")) or _safe_text(raw.get("Application"))
                species_reactivity_text = _safe_text(raw.get("Species Reactivity"))
                target_aliases = _extract_antibody_target_aliases(canonical_name)
                alias_records = _build_alias_records(
                    ("canonical_name", canonical_name),
                    ("catalog_no", catalog_no),
                    *[("target_antigen", value) for value in target_aliases],
                    *[("synonym", value) for value in _split_aliases(raw.get("Also known as "))],
                )
                alias_records = _expand_antibody_alias_records(alias_records)

                entries.append(
                    ProductRegistryEntry(
                        catalog_no=catalog_no,
                        canonical_name=canonical_name,
                        business_line="antibody",
                        aliases=tuple(record.value for record in alias_records),
                        target_antigen=target_aliases[0] if target_aliases else "",
                        application_text=application_text,
                        species_reactivity_text=species_reactivity_text,
                        clone=_safe_text(raw.get("clone")),
                        clonality=_infer_antibody_clonality(sheet_name, canonical_name),
                        isotype=_safe_text(raw.get("Isotype")),
                        ig_class=_safe_text(raw.get("Ig class")),
                        gene_id=_safe_text(raw.get("Gene ID")),
                        gene_accession=_safe_text(raw.get("Gene Accession")),
                        swissprot=_safe_text(raw.get("Swissprot")),
                        source_file=path.name,
                        source_sheet=sheet_name,
                    )
                )

        return entries

    def _build_cart_entries(self) -> list[ProductRegistryEntry]:
        path = self._data_files["car_t"]
        df = pd.read_excel(path, sheet_name="Sheet1")
        entries: list[ProductRegistryEntry] = []

        for _, raw in df.iterrows():
            catalog_no = _safe_text(raw.get("catalog_no"))
            canonical_name = _generate_cart_name(raw)
            if not catalog_no or not canonical_name:
                continue

            alias_records = _build_alias_records(
                ("canonical_name", canonical_name),
                ("catalog_no", catalog_no),
                ("target_antigen", _safe_text(raw.get("target_antigen"))),
                ("group_name", _safe_text(raw.get("group_name"))),
                ("construct", _safe_text(raw.get("construct"))),
                ("marker", _safe_text(raw.get("marker"))),
            )

            entries.append(
                ProductRegistryEntry(
                    catalog_no=catalog_no,
                    canonical_name=canonical_name,
                    business_line="car_t",
                    aliases=tuple(record.value for record in alias_records),
                    target_antigen=_safe_text(raw.get("target_antigen")),
                    costimulatory_domain=_safe_text(raw.get("costimulatory_domain")),
                    construct=_safe_text(raw.get("construct")),
                    group_name=_safe_text(raw.get("group_name")),
                    group_type=_safe_text(raw.get("group_type")),
                    group_subtype=_safe_text(raw.get("group_subtype")),
                    group_summary=_safe_text(raw.get("group_summary")),
                    price_usd=_safe_text(raw.get("price_usd")),
                    unit=_safe_text(raw.get("unit")),
                    cell_number=_safe_text(raw.get("cell_number")),
                    marker=_safe_text(raw.get("marker")),
                    source_file=path.name,
                    source_sheet="Sheet1",
                )
            )

        return entries

    def _build_mrna_entries(self) -> list[ProductRegistryEntry]:
        path = self._data_files["mrna_lnp"]
        df = pd.read_excel(path, sheet_name="Sheet1")
        entries: list[ProductRegistryEntry] = []

        for _, raw in df.iterrows():
            catalog_no = _safe_text(raw.get("catalog_no"))
            canonical_name = _safe_text(raw.get("name"))
            if not catalog_no or not canonical_name:
                continue

            format_or_size = _safe_text(raw.get("format"))
            product_type = _safe_text(raw.get("type"))
            alias_records = _build_alias_records(
                ("canonical_name", canonical_name),
                ("catalog_no", catalog_no),
                ("product_type", product_type),
                ("format_or_size", format_or_size),
                ("platform", "mRNA-Lipid Nanoparticle"),
            )
            alias_records = _expand_mrna_lnp_alias_records(alias_records)

            entries.append(
                ProductRegistryEntry(
                    catalog_no=catalog_no,
                    canonical_name=canonical_name,
                    business_line="mrna_lnp",
                    aliases=tuple(record.value for record in alias_records),
                    application_text=format_or_size,
                    format_or_size=format_or_size,
                    product_type=product_type,
                    price_usd=_safe_text(raw.get("price_usd")),
                    source_file=path.name,
                    source_sheet="Sheet1",
                )
            )

        return entries


class PostgresProductRegistrySource:
    def __init__(self, dsn: str, table_name: str = PRODUCT_REGISTRY_TABLE) -> None:
        self._dsn = dsn
        self._table_name = table_name

    def load_entries(self) -> tuple[ProductRegistryEntry, ...]:
        query = f"""
            SELECT
                catalog_no,
                canonical_name,
                business_line,
                aliases,
                target_antigen,
                application_text,
                species_reactivity_text,
                format_or_size,
                clone,
                clonality,
                isotype,
                ig_class,
                gene_id,
                gene_accession,
                swissprot,
                costimulatory_domain,
                construct,
                product_type,
                group_name,
                group_type,
                group_subtype,
                group_summary,
                price_usd,
                unit,
                cell_number,
                marker,
                source_file,
                source_sheet
            FROM {self._table_name}
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(query)
                rows = cur.fetchall()

        return tuple(_entry_from_record(row) for row in rows)


def get_product_registry_source() -> ProductRegistrySource:
    backend = PRODUCT_REGISTRY_BACKEND
    if backend == "postgres":
        dsn = _postgres_dsn()
        if not dsn:
            raise ValueError("OBJECTS_PRODUCT_REGISTRY_BACKEND is postgres but no PostgreSQL DSN is configured.")
        return PostgresProductRegistrySource(dsn=dsn)
    return ExcelProductRegistrySource()


@lru_cache(maxsize=1)
def load_product_registry() -> tuple[ProductRegistryEntry, ...]:
    return get_product_registry_source().load_entries()


@lru_cache(maxsize=1)
def get_product_registry_payload() -> dict[str, Any]:
    entries = load_product_registry()
    by_catalog_no: dict[str, dict[str, Any]] = {}
    alias_to_catalog_nos: dict[str, list[str]] = {}
    alias_to_match_records: dict[str, list[dict[str, str]]] = {}

    for entry in entries:
        payload = _entry_payload(entry)
        by_catalog_no[entry.catalog_no] = payload
        for alias_record in _alias_records_for_entry(entry):
            normalized = normalize_object_alias(alias_record.value)
            if not normalized:
                continue
            alias_to_catalog_nos.setdefault(normalized, [])
            if entry.catalog_no not in alias_to_catalog_nos[normalized]:
                alias_to_catalog_nos[normalized].append(entry.catalog_no)
            alias_to_match_records.setdefault(normalized, [])
            alias_to_match_records[normalized].append(
                {
                    "catalog_no": entry.catalog_no,
                    "canonical_name": entry.canonical_name,
                    "alias_value": alias_record.value,
                    "alias_kind": alias_record.alias_kind,
                    "business_line": entry.business_line,
                }
            )

    return {
        "entries": list(by_catalog_no.values()),
        "by_catalog_no": by_catalog_no,
        "alias_to_catalog_nos": alias_to_catalog_nos,
        "alias_to_match_records": alias_to_match_records,
    }


def lookup_products_by_alias(alias: str) -> list[dict[str, Any]]:
    normalized = normalize_object_alias(alias)
    if not normalized:
        return []
    payload = get_product_registry_payload()
    catalog_nos = payload["alias_to_catalog_nos"].get(normalized, [])
    return [
        payload["by_catalog_no"][catalog_no]
        for catalog_no in catalog_nos
        if catalog_no in payload["by_catalog_no"]
    ]


def lookup_product_alias_matches(alias: str) -> list[dict[str, str]]:
    normalized = normalize_object_alias(alias)
    if not normalized:
        return []
    payload = get_product_registry_payload()
    return payload["alias_to_match_records"].get(normalized, [])


def lookup_product_by_catalog_no(catalog_no: str) -> dict[str, Any] | None:
    normalized = _safe_text(catalog_no)
    if not normalized:
        return None
    return get_product_registry_payload()["by_catalog_no"].get(normalized)


def canonicalize_product_name(value: str) -> str:
    cleaned = _safe_text(value)
    matches = lookup_products_by_alias(cleaned)
    if len(matches) == 1:
        canonical_name = _safe_text(matches[0].get("canonical_name"))
        if canonical_name:
            return canonical_name
    return cleaned


def _postgres_dsn() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    host = os.getenv("PGHOST", "localhost").strip()
    port = os.getenv("PGPORT", "5432").strip()
    user = os.getenv("PGUSER", "postgres").strip()
    password = os.getenv("PGPASSWORD", "").strip()
    database = os.getenv("PGDATABASE", "").strip()
    if not database:
        return ""
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"
    return f"postgresql://{user}@{host}:{port}/{database}"


def _entry_payload(entry: ProductRegistryEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["aliases"] = list(entry.aliases)
    payload["alias_records"] = [asdict(record) for record in _alias_records_for_entry(entry)]
    return payload


def _entry_from_record(record: dict[str, Any]) -> ProductRegistryEntry:
    aliases = record.get("aliases", ())
    if isinstance(aliases, str):
        aliases = _split_aliases(aliases)
    elif isinstance(aliases, list):
        aliases = [clean_text(alias) for alias in aliases if clean_text(alias)]
    return ProductRegistryEntry(
        catalog_no=_safe_text(record.get("catalog_no")),
        canonical_name=_safe_text(record.get("canonical_name")),
        business_line=_safe_text(record.get("business_line")),
        aliases=tuple(dedupe_preserve_order(list(aliases))),
        target_antigen=_safe_text(record.get("target_antigen")),
        application_text=_safe_text(record.get("application_text")),
        species_reactivity_text=_safe_text(record.get("species_reactivity_text")),
        format_or_size=_safe_text(record.get("format_or_size")),
        clone=_safe_text(record.get("clone")),
        clonality=_safe_text(record.get("clonality")),
        isotype=_safe_text(record.get("isotype")),
        ig_class=_safe_text(record.get("ig_class")),
        gene_id=_safe_text(record.get("gene_id")),
        gene_accession=_safe_text(record.get("gene_accession")),
        swissprot=_safe_text(record.get("swissprot")),
        costimulatory_domain=_safe_text(record.get("costimulatory_domain")),
        construct=_safe_text(record.get("construct")),
        product_type=_safe_text(record.get("product_type")),
        group_name=_safe_text(record.get("group_name")),
        group_type=_safe_text(record.get("group_type")),
        group_subtype=_safe_text(record.get("group_subtype")),
        group_summary=_safe_text(record.get("group_summary")),
        price_usd=_safe_text(record.get("price_usd")),
        unit=_safe_text(record.get("unit")),
        cell_number=_safe_text(record.get("cell_number")),
        marker=_safe_text(record.get("marker")),
        source_file=_safe_text(record.get("source_file")),
        source_sheet=_safe_text(record.get("source_sheet")),
    )


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return clean_text(value)


def _split_aliases(value: Any) -> list[str]:
    text = _safe_text(value)
    if not text:
        return []
    aliases: list[str] = []
    for raw in text.replace(";", ",").split(","):
        alias = _safe_text(raw)
        if alias:
            aliases.append(alias)
    return dedupe_preserve_order(aliases)


def _expand_mrna_lnp_aliases(values: list[str]) -> list[str]:
    expanded: list[str] = list(values)
    for value in values:
        alias = _safe_text(value)
        lowered = alias.lower()
        if "mrna-lnp" in lowered:
            expanded.append(alias.replace("mRNA-LNP", "mRNA-Lipid Nanoparticle"))
            expanded.append(alias.replace("mrna-lnp", "mrna-lipid nanoparticle"))
        if "mrna lnp" in lowered:
            expanded.append(alias.replace("mRNA LNP", "mRNA Lipid Nanoparticle"))
            expanded.append(alias.replace("mrna lnp", "mrna lipid nanoparticle"))
    return dedupe_preserve_order(expanded)


def _expand_mrna_lnp_alias_records(records: list[ProductAliasRecord]) -> list[ProductAliasRecord]:
    expanded: list[ProductAliasRecord] = list(records)
    for record in records:
        alias = _safe_text(record.value)
        lowered = alias.lower()
        if "mrna-lnp" in lowered:
            expanded.append(ProductAliasRecord(alias.replace("mRNA-LNP", "mRNA-Lipid Nanoparticle"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("mrna-lnp", "mrna-lipid nanoparticle"), record.alias_kind))
        if "mrna lnp" in lowered:
            expanded.append(ProductAliasRecord(alias.replace("mRNA LNP", "mRNA Lipid Nanoparticle"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("mrna lnp", "mrna lipid nanoparticle"), record.alias_kind))
    return _dedupe_alias_records(expanded)


def _extract_antibody_target_aliases(canonical_name: str) -> list[str]:
    cleaned = _safe_text(canonical_name)
    lowered = cleaned.lower()
    marker = " antibody to "
    if marker not in lowered:
        return []
    target = cleaned[lowered.index(marker) + len(marker):].strip()
    if not target:
        return []
    aliases = [target]
    stripped_variant = target.rsplit("(", 1)[0].strip() if ")" in target else target
    if stripped_variant and stripped_variant != target:
        aliases.append(stripped_variant)
    return dedupe_preserve_order(aliases)


def _expand_antibody_alias_variants(values: list[str]) -> list[str]:
    expanded: list[str] = list(values)
    for value in values:
        alias = _safe_text(value)
        lowered = alias.lower().replace("×", "x")
        if "6 his" in lowered or "6xhis" in lowered:
            expanded.append(alias.replace("6×His", "6xHis").replace("6 His", "6xHis"))
            expanded.append(alias.replace("6xHis", "6×His"))
            expanded.append(alias.replace("6xHis", "6 His"))
    return dedupe_preserve_order(expanded)


def _expand_antibody_alias_records(records: list[ProductAliasRecord]) -> list[ProductAliasRecord]:
    expanded: list[ProductAliasRecord] = list(records)
    for record in records:
        alias = _safe_text(record.value)
        lowered = alias.lower().replace("×", "x")
        if "6 his" in lowered or "6xhis" in lowered:
            expanded.append(ProductAliasRecord(alias.replace("6×His", "6xHis").replace("6 His", "6xHis"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("6xHis", "6×His"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("6xHis", "6 His"), record.alias_kind))
    return _dedupe_alias_records(expanded)


def _build_alias_records(*pairs: tuple[str, str]) -> list[ProductAliasRecord]:
    records = [
        ProductAliasRecord(value=_safe_text(value), alias_kind=alias_kind)
        for alias_kind, value in pairs
        if _safe_text(value)
    ]
    return _dedupe_alias_records(records)


def _dedupe_alias_records(records: list[ProductAliasRecord]) -> list[ProductAliasRecord]:
    deduped: list[ProductAliasRecord] = []
    seen: set[tuple[str, str]] = set()
    seen_normalized_values: set[str] = set()
    for record in records:
        normalized = normalize_object_alias(record.value)
        if not normalized:
            continue
        identity = (normalized, record.alias_kind)
        if identity in seen:
            continue
        if normalized in seen_normalized_values and record.alias_kind in {"canonical_name", "catalog_no"}:
            continue
        seen.add(identity)
        seen_normalized_values.add(normalized)
        deduped.append(ProductAliasRecord(value=record.value, alias_kind=record.alias_kind))
    ordered_values = dedupe_preserve_order([record.value for record in deduped])
    final_records: list[ProductAliasRecord] = []
    for value in ordered_values:
        normalized = normalize_object_alias(value)
        for record in deduped:
            if normalize_object_alias(record.value) == normalized:
                final_records.append(record)
                break
    return final_records


def _alias_records_for_entry(entry: ProductRegistryEntry) -> list[ProductAliasRecord]:
    if entry.business_line == "antibody":
        return _dedupe_alias_records(
            _build_alias_records(
                ("canonical_name", entry.canonical_name),
                ("catalog_no", entry.catalog_no),
                ("target_antigen", entry.target_antigen),
                *[("synonym", alias) for alias in entry.aliases if alias not in {entry.canonical_name, entry.catalog_no, entry.target_antigen}],
            )
        )
    if entry.business_line == "car_t":
        return _dedupe_alias_records(
            _build_alias_records(
                ("canonical_name", entry.canonical_name),
                ("catalog_no", entry.catalog_no),
                ("target_antigen", entry.target_antigen),
                ("group_name", entry.group_name),
                ("construct", entry.construct),
                ("marker", entry.marker),
                *[("synonym", alias) for alias in entry.aliases if alias not in {entry.canonical_name, entry.catalog_no, entry.target_antigen, entry.group_name, entry.construct, entry.marker}],
            )
        )
    return _dedupe_alias_records(
        _build_alias_records(
            ("canonical_name", entry.canonical_name),
            ("catalog_no", entry.catalog_no),
            ("product_type", entry.product_type),
            ("format_or_size", entry.format_or_size),
            *[("synonym", alias) for alias in entry.aliases if alias not in {entry.canonical_name, entry.catalog_no, entry.product_type, entry.format_or_size}],
        )
    )


def _infer_antibody_clonality(sheet_name: str, canonical_name: str) -> str:
    lowered = canonical_name.lower()
    if "monoclonal" in lowered or "Monoclonal" in sheet_name:
        return "monoclonal"
    if "polyclonal" in lowered or "Polyclonal" in sheet_name:
        return "polyclonal"
    return ""


def _generate_cart_name(raw: pd.Series) -> str:
    explicit_name = _safe_text(raw.get("name"))
    if explicit_name:
        return explicit_name
    parts = [
        _safe_text(raw.get("target_antigen")),
        _safe_text(raw.get("costimulatory_domain")),
        "CAR-T",
    ]
    return clean_text(" ".join(part for part in parts if part))
