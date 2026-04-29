from __future__ import annotations

import os
import re
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
PRODUCT_REGISTRY_TABLE = os.getenv("OBJECTS_PRODUCT_REGISTRY_TABLE", "product_catalog")


@dataclass(frozen=True)
class ProductRegistryEntry:
    catalog_no: str
    canonical_name: str
    business_line: str
    aliases: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    target_antigen: str = ""
    application_text: str = ""
    applications: tuple[str, ...] = ()
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
                synonyms = _split_aliases(raw.get("Also known as "))
                clonality = _infer_antibody_clonality(sheet_name, canonical_name)
                alias_records = _build_alias_records(
                    ("canonical_name", canonical_name),
                    ("catalog_no", catalog_no),
                    *[("target_antigen", value) for value in target_aliases],
                    *[("synonym", value) for value in synonyms],
                )
                alias_records = _expand_antibody_alias_records(
                    alias_records,
                    target_aliases=target_aliases,
                    synonyms=synonyms,
                    clonality=clonality,
                )

                entries.append(
                    ProductRegistryEntry(
                        catalog_no=catalog_no,
                        canonical_name=canonical_name,
                        business_line="antibody",
                        aliases=tuple(record.value for record in alias_records),
                        synonyms=tuple(synonyms),
                        target_antigen=target_aliases[0] if target_aliases else "",
                        application_text=application_text,
                        applications=_normalize_application_tokens(application_text),
                        species_reactivity_text=species_reactivity_text,
                        clone=_safe_text(raw.get("clone")),
                        clonality=clonality,
                        isotype=_normalize_isotype(raw.get("Isotype")),
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

            target_antigen = _safe_text(raw.get("target_antigen"))
            construct = _safe_text(raw.get("construct"))
            alias_records = _build_alias_records(
                ("canonical_name", canonical_name),
                ("catalog_no", catalog_no),
                ("target_antigen", target_antigen),
                ("group_name", _safe_text(raw.get("group_name"))),
                ("construct", construct),
                ("marker", _safe_text(raw.get("marker"))),
            )
            alias_records = _expand_cart_alias_records(
                alias_records,
                target_antigen=target_antigen,
                construct=construct,
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
            alias_records = _expand_mrna_lnp_alias_records(
                alias_records,
                canonical_name=canonical_name,
            )

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


def iter_product_alias_records() -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for entry in load_product_registry():
        catalog_no = _safe_text(entry.catalog_no)
        if not catalog_no:
            continue
        for record in _alias_records_for_entry(entry):
            alias_value = _safe_text(record.value)
            if not alias_value:
                continue
            normalized = normalize_object_alias(alias_value)
            if not normalized:
                continue
            rows.append((catalog_no, alias_value, normalized, record.alias_kind or ""))
    return rows


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
    payload["applications"] = list(entry.applications)
    payload["alias_records"] = [asdict(record) for record in _alias_records_for_entry(entry)]
    return payload


def _entry_from_record(record: dict[str, Any]) -> ProductRegistryEntry:
    aliases = record.get("aliases", ())
    if isinstance(aliases, str):
        aliases = _split_aliases(aliases)
    elif isinstance(aliases, list):
        aliases = [clean_text(alias) for alias in aliases if clean_text(alias)]
    synonyms = record.get("synonyms", ())
    if isinstance(synonyms, str):
        synonyms = _split_aliases(synonyms)
    elif isinstance(synonyms, list):
        synonyms = [clean_text(syn) for syn in synonyms if clean_text(syn)]
    application_text = _safe_text(record.get("application_text"))
    return ProductRegistryEntry(
        catalog_no=_safe_text(record.get("catalog_no")),
        canonical_name=_safe_text(record.get("canonical_name")),
        business_line=_safe_text(record.get("business_line")),
        aliases=tuple(dedupe_preserve_order(list(aliases))),
        synonyms=tuple(dedupe_preserve_order(list(synonyms))),
        target_antigen=_safe_text(record.get("target_antigen")),
        application_text=application_text,
        applications=_normalize_application_tokens(application_text),
        species_reactivity_text=_safe_text(record.get("species_reactivity_text")),
        format_or_size=_safe_text(record.get("format_or_size")),
        clone=_safe_text(record.get("clone")),
        clonality=_safe_text(record.get("clonality")),
        isotype=_normalize_isotype(record.get("isotype")),
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


_ISOTYPE_HEAVY_RE = re.compile(
    r"\big\s*(g[1-4][a-c]?|g|m|a|d|e)\b",
    re.IGNORECASE,
)
_ISOTYPE_LIGHT_RE = re.compile(r"(kappa|κ|lambda|λ)", re.IGNORECASE)


def _normalize_isotype(raw: Any) -> str:
    """Collapse the dirty Excel ``Isotype`` column into canonical heavy-chain form.

    Examples::

        'Mouse  IgG1' / 'mouse IgG1' / 'Mouse IGg1' -> 'IgG1'
        'Mouse Ig M' -> 'IgM'
        'Mouse IgG1,kappa' / 'Mouse IgG1.kappa' -> 'IgG1/kappa'
        'Mouse IgG2b/Mouse IgG2a' -> 'IgG_mixed'
        'Rat Mab' / '' / NaN -> ''
    """
    text = _safe_text(raw).lower()
    if not text:
        return ""

    heavy_matches = _ISOTYPE_HEAVY_RE.findall(text)
    if not heavy_matches:
        return ""

    canonical_seen: list[str] = []
    for suffix in heavy_matches:
        compact = re.sub(r"\s+", "", suffix).lower()
        if compact.startswith("g"):
            canonical = "IgG" + compact[1:].lower()
        else:
            canonical = "Ig" + compact.upper()
        if canonical not in canonical_seen:
            canonical_seen.append(canonical)

    if len(canonical_seen) > 1:
        return "IgG_mixed"

    primary = canonical_seen[0]
    light_match = _ISOTYPE_LIGHT_RE.search(text)
    if light_match:
        light = light_match.group(1).lower().replace("κ", "kappa").replace("λ", "lambda")
        return f"{primary}/{light}"
    return primary


_APPLICATION_CANONICAL = {
    "elisa": "ELISA",
    "western blot": "WB",
    "wb": "WB",
    "ihc-p": "IHC",
    "ihc-f": "IHC",
    "ihc": "IHC",
    "icc": "ICC",
    "immunofluorescence": "IF",
    "if": "IF",
    "flow cytometry": "FCM",
    "facs": "FCM",
    "flow": "FCM",
    "fcm": "FCM",
    "fc": "FCM",
    "co-ip": "IP",
    "immunoprecipitation": "IP",
    "ip": "IP",
}


def _normalize_application_tokens(raw: Any) -> tuple[str, ...]:
    """Pick canonical application codes out of noisy free text.

    Handles delimiter slop (commas, plusses, slashes, full-width punctuation)
    and adjoined tokens such as ``ELISAFCM`` by greedy left-to-right matching
    against the canonical vocabulary. Anything not in the vocabulary is dropped.
    """
    text = _safe_text(raw).lower()
    if not text:
        return ()

    text = re.sub(r"[+?/、,，。.\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ()

    keys_by_len = sorted(_APPLICATION_CANONICAL.keys(), key=len, reverse=True)
    found: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == " ":
            cursor += 1
            continue
        matched = False
        for key in keys_by_len:
            if text.startswith(key, cursor):
                canonical = _APPLICATION_CANONICAL[key]
                if canonical not in found:
                    found.append(canonical)
                cursor += len(key)
                matched = True
                break
        if not matched:
            cursor += 1
    return tuple(found)


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


_MRNA_LNP_SUFFIXES = (
    " mRNA-Lipid Nanoparticle",
    " mRNA Lipid Nanoparticle",
    " mRNA-LNP",
    " mRNA LNP",
)
_TRAILING_PARENS_RE = re.compile(r"\s*\([^()]*\)\s*$")
_ANY_PARENS_RE = re.compile(r"\s*\([^()]*\)\s*")


def _mrna_lnp_bare_names(canonical_name: str) -> list[str]:
    text = _safe_text(canonical_name)
    if not text:
        return []
    trimmed = text
    while True:
        stripped = _TRAILING_PARENS_RE.sub("", trimmed).strip()
        if stripped == trimmed or not stripped:
            break
        trimmed = stripped
    lowered = trimmed.lower()
    bare = trimmed
    for suffix in _MRNA_LNP_SUFFIXES:
        if lowered.endswith(suffix.lower()):
            bare = trimmed[: len(trimmed) - len(suffix)].strip()
            break
    else:
        for suffix in _MRNA_LNP_SUFFIXES:
            idx = lowered.find(suffix.lower())
            if idx > 0:
                bare = trimmed[:idx].strip()
                break
    variants: list[str] = []
    if bare:
        variants.append(bare)
    bare_no_parens = _ANY_PARENS_RE.sub(" ", bare).strip()
    bare_no_parens = re.sub(r"\s+", " ", bare_no_parens)
    if bare_no_parens and bare_no_parens not in variants:
        variants.append(bare_no_parens)
    return variants


def _expand_mrna_lnp_alias_records(
    records: list[ProductAliasRecord],
    *,
    canonical_name: str = "",
) -> list[ProductAliasRecord]:
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

    for bare in _mrna_lnp_bare_names(canonical_name):
        for variant in (
            bare,
            f"{bare} mRNA",
            f"{bare} LNP",
            f"{bare} mRNA LNP",
            f"{bare} mRNA-LNP",
            f"{bare} mRNA Lipid Nanoparticle",
            f"{bare} mRNA-Lipid Nanoparticle",
        ):
            expanded.append(ProductAliasRecord(variant, "target_antigen"))

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


_CART_TARGET_SPLIT_RE = re.compile(r"\s*[+/&]\s*")


def _cart_target_variants(target_antigen: str) -> list[str]:
    target = _safe_text(target_antigen)
    if not target:
        return []
    parts = [p.strip() for p in _CART_TARGET_SPLIT_RE.split(target) if p.strip()]
    variants = [target]
    if len(parts) > 1:
        for part in parts:
            if part and part not in variants:
                variants.append(part)
    return variants


def _expand_cart_alias_records(
    records: list[ProductAliasRecord],
    *,
    target_antigen: str,
    construct: str,
) -> list[ProductAliasRecord]:
    variants = _cart_target_variants(target_antigen)
    if not variants:
        return _dedupe_alias_records(records)

    construct_compact = _safe_text(construct).lower().replace(" ", "")
    expanded: list[ProductAliasRecord] = list(records)

    for variant in variants:
        expanded.append(ProductAliasRecord(f"{variant} CAR", "target_antigen"))
        expanded.append(ProductAliasRecord(f"{variant} CAR-T", "target_antigen"))
        expanded.append(ProductAliasRecord(f"{variant} CAR T", "target_antigen"))
        if variant.lower() == "mock":
            continue
        expanded.append(ProductAliasRecord(f"Anti-{variant} CAR", "target_antigen"))
        expanded.append(ProductAliasRecord(f"Anti-{variant} CAR-T", "target_antigen"))
        expanded.append(ProductAliasRecord(f"anti {variant} CAR", "target_antigen"))
        variant_compact = variant.lower().replace(" ", "").replace("-", "")
        if variant_compact and construct_compact.startswith("hu" + variant_compact):
            expanded.append(ProductAliasRecord(f"hu{variant} CAR", "target_antigen"))
            expanded.append(ProductAliasRecord(f"hu{variant} CAR-T", "target_antigen"))
            expanded.append(ProductAliasRecord(f"humanized {variant} CAR", "target_antigen"))
            expanded.append(ProductAliasRecord(f"humanized {variant} CAR-T", "target_antigen"))
            expanded.append(ProductAliasRecord(f"Anti-hu{variant} CAR", "target_antigen"))

    return _dedupe_alias_records(expanded)


def _antibody_target_variants(target_aliases: list[str], synonyms: list[str]) -> list[str]:
    variants: list[str] = []
    for value in [*target_aliases, *synonyms]:
        cleaned = _safe_text(value)
        if not cleaned or cleaned in variants:
            continue
        variants.append(cleaned)
    return variants


def _expand_antibody_alias_records(
    records: list[ProductAliasRecord],
    *,
    target_aliases: list[str] | None = None,
    synonyms: list[str] | None = None,
    clonality: str = "",
) -> list[ProductAliasRecord]:
    expanded: list[ProductAliasRecord] = list(records)
    for record in records:
        alias = _safe_text(record.value)
        lowered = alias.lower().replace("×", "x")
        if "6 his" in lowered or "6xhis" in lowered:
            expanded.append(ProductAliasRecord(alias.replace("6×His", "6xHis").replace("6 His", "6xHis"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("6xHis", "6×His"), record.alias_kind))
            expanded.append(ProductAliasRecord(alias.replace("6xHis", "6 His"), record.alias_kind))

    variants = _antibody_target_variants(target_aliases or [], synonyms or [])
    clonality_lower = (clonality or "").strip().lower()
    for variant in variants:
        expanded.append(ProductAliasRecord(f"{variant} antibody", "target_antigen"))
        expanded.append(ProductAliasRecord(f"Anti-{variant} antibody", "target_antigen"))
        expanded.append(ProductAliasRecord(f"Anti-{variant}", "target_antigen"))
        expanded.append(ProductAliasRecord(f"anti-{variant}", "target_antigen"))
        expanded.append(ProductAliasRecord(f"anti {variant}", "target_antigen"))
        expanded.append(ProductAliasRecord(f"{variant} mAb", "target_antigen"))
        expanded.append(ProductAliasRecord(f"Anti-{variant} mAb", "target_antigen"))
        if clonality_lower == "monoclonal":
            expanded.append(ProductAliasRecord(f"{variant} monoclonal antibody", "target_antigen"))
            expanded.append(ProductAliasRecord(f"{variant} monoclonal", "target_antigen"))
            expanded.append(ProductAliasRecord(f"Anti-{variant} monoclonal antibody", "target_antigen"))
        if clonality_lower == "polyclonal":
            expanded.append(ProductAliasRecord(f"{variant} polyclonal antibody", "target_antigen"))
            expanded.append(ProductAliasRecord(f"{variant} polyclonal", "target_antigen"))
            expanded.append(ProductAliasRecord(f"{variant} pAb", "target_antigen"))
            expanded.append(ProductAliasRecord(f"Anti-{variant} polyclonal antibody", "target_antigen"))

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
        target_aliases = _extract_antibody_target_aliases(entry.canonical_name)
        synonyms = list(entry.synonyms)
        base_records = _build_alias_records(
            ("canonical_name", entry.canonical_name),
            ("catalog_no", entry.catalog_no),
            *[("target_antigen", value) for value in target_aliases],
            *[("synonym", syn) for syn in synonyms],
        )
        return _expand_antibody_alias_records(
            base_records,
            target_aliases=target_aliases,
            synonyms=synonyms,
            clonality=entry.clonality,
        )
    if entry.business_line == "car_t":
        base_records = _build_alias_records(
            ("canonical_name", entry.canonical_name),
            ("catalog_no", entry.catalog_no),
            ("target_antigen", entry.target_antigen),
            ("group_name", entry.group_name),
            ("construct", entry.construct),
            ("marker", entry.marker),
        )
        return _expand_cart_alias_records(
            base_records,
            target_antigen=entry.target_antigen,
            construct=entry.construct,
        )
    if entry.business_line == "mrna_lnp":
        base_records = _build_alias_records(
            ("canonical_name", entry.canonical_name),
            ("catalog_no", entry.catalog_no),
            ("product_type", entry.product_type),
            ("format_or_size", entry.format_or_size),
            ("platform", "mRNA-Lipid Nanoparticle"),
        )
        return _expand_mrna_lnp_alias_records(
            base_records,
            canonical_name=entry.canonical_name,
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
