from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import psycopg

from src.objects.normalizers import clean_text, dedupe_preserve_order, normalize_object_alias


BASE_DIR = Path(__file__).resolve().parents[3]
SERVICE_PAGE_SOURCE_DIRS = [
    BASE_DIR / "data" / "processed" / "rag_ready_files" / "car-t:car-nk",
    BASE_DIR / "data" / "processed" / "rag_ready_files" / "mrna-lnp",
    BASE_DIR / "data" / "processed" / "rag_ready_files" / "antibody",
    BASE_DIR / "data" / "processed" / "rag_ready_files" / "cell-based-assays",
    BASE_DIR / "data" / "processed" / "rag_ready_files" / "protein-expression",
]
SERVICE_REGISTRY_BACKEND = (os.getenv("OBJECTS_SERVICE_REGISTRY_BACKEND") or "auto").strip().lower()
SERVICE_REGISTRY_TABLE = os.getenv("OBJECTS_SERVICE_REGISTRY_TABLE", "service_catalog")
SERVICE_PAGE_FILE_PATTERN = re.compile(r"promab_.*_rag_ready(?:_.*)?\.txt$", re.I)
_KEY_VALUE_PATTERN = re.compile(r"^([A-Za-z0-9_ /()+&.-]+):\s*(.*)$")

# Canonical Layer-1 taxonomy. Single source of truth for every consumer that
# needs to validate a business_line string (corpus hints, LLM-produced facts,
# RAG soft-boost guards). Must stay aligned with the business_line values
# emitted by service_page_ingestion into each service's metadata.
KNOWN_BUSINESS_LINES: frozenset[str] = frozenset({
    "antibody",
    "car_t_car_nk",
    "cell_based_assays",
    "mrna_lnp",
    "protein_expression",
})

MANUAL_SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "mRNA-LNP Gene Delivery": (
        "mRNA LNP Gene Delivery",
        "mRNA-LNP delivery",
        "mRNA LNP delivery",
        "LNP gene delivery",
        "LNP delivery",
        "mRNA Lipid Nanoparticle Gene Delivery",
        "mRNA-LNP",
        "mRNA LNP",
        "mRNA LNP development",
    ),
    # The three species-specific monoclonal services share the bare
    # "monoclonal antibody" / "monoclonal antibodies" / "mAb" aliases on
    # purpose: when a customer says it without species, the alias index
    # surfaces all three canonicals so service_extractor's multi-match
    # branch fires AmbiguousObjectSet → routing emits
    # object_disambiguation clarify rather than picking one arbitrarily.
    "Mouse Monoclonal Antibodies": (
        "Mouse Monoclonal Antibody Service",
        "Mouse Monoclonal Antibody Development",
        "mouse monoclonal",
        "mouse mAb",
        "monoclonal antibody",
        "monoclonal antibodies",
        "mAb",
    ),
    "Rabbit Monoclonal Antibodies": (
        "Rabbit Monoclonal Antibody Service",
        "Rabbit Monoclonal Antibody Development",
        "rabbit monoclonal",
        "rabbit mAb",
        "monoclonal antibody",
        "monoclonal antibodies",
        "mAb",
    ),
    "Human Monoclonal Antibodies": (
        "human monoclonal",
        "human mAb",
        "monoclonal antibody",
        "monoclonal antibodies",
        "mAb",
    ),
    "Rabbit Polyclonal Antibody Production": (
        "Rabbit Polyclonal Antibodies",
        "Rabbit Polyclonal Antibody Service",
        "rabbit polyclonal",
    ),
    "Bispecific Antibody Development": (
        "bispecific",
        "bispecific mAb",
    ),
    "Affinity Tune-Up & Humanization": (
        "humanization",
        "affinity tune-up",
        "affinity maturation",
    ),
    "CAR-T Cell Design and Development": (
        "Custom CAR-T Cell Development",
        "CAR-T Development",
        "CAR-T cell therapy",
        "CAR-T therapy",
        "CAR-T cell therapy development",
    ),
    "Custom CAR-NK Manufacturing": (
        "CAR-NK",
        "CAR-NK development",
        "CAR-NK service",
    ),
    "Custom CAR-Macrophage Cell Development": (
        "CAR-macrophage",
        "CAR-M",
        "CAR macrophage development",
    ),
    "Stable Cell Line Development": (
        "stable cell line service",
        # CHO is shared with Mammalian Protein Expression on purpose so a
        # bare "CHO" / "CHO work" surfaces multi-match → ambiguous_set.
        "CHO",
        "CHO cell line",
    ),
    "T Cell Activation and Proliferation Assay": (
        "T cell activation",
        "T cell proliferation",
    ),
    "Lentivirus Production": (
        "lentivirus",
    ),
    "E. coli Protein Expression": (
        "E. coli expression",
        "E coli expression",
    ),
    "Mammalian Protein Expression": (
        "mammalian expression",
        # See note on Stable Cell Line Development — CHO intentionally
        # ambiguous between the two services.
        "CHO",
        "CHO cell line",
    ),
    "Baculovirus Protein Expression": (
        "baculovirus expression",
        "insect cell expression",
    ),
}


@dataclass(frozen=True)
class ServiceAliasRecord:
    value: str
    alias_kind: str


@dataclass(frozen=True)
class ServiceRegistryEntry:
    canonical_name: str
    business_line: str
    aliases: tuple[str, ...] = ()
    service_line: str = ""
    subcategory: str = ""
    page_title: str = ""
    document_summary: str = ""
    source_url: str = ""
    source_path: str = ""
    source_file: str = ""


class ServiceRegistrySource(Protocol):
    def load_entries(self) -> tuple[ServiceRegistryEntry, ...]:
        ...


class FilesServiceRegistrySource:
    def __init__(self, source_dirs: list[Path] | None = None) -> None:
        self._source_dirs = source_dirs or SERVICE_PAGE_SOURCE_DIRS

    def load_entries(self) -> tuple[ServiceRegistryEntry, ...]:
        by_service_name: dict[str, ServiceRegistryEntry] = {}
        for path in _iter_service_page_files(self._source_dirs):
            metadata = _parse_document_metadata(path)
            canonical_name = clean_text(metadata.get("service_name"))
            if not canonical_name:
                continue
            by_service_name.setdefault(
                canonical_name,
                ServiceRegistryEntry(
                    canonical_name=canonical_name,
                    business_line=clean_text(metadata.get("business_line")),
                    aliases=tuple(
                        dedupe_preserve_order(
                            [
                                canonical_name,
                                *MANUAL_SERVICE_ALIASES.get(canonical_name, ()),
                            ]
                        )
                    ),
                    service_line=clean_text(metadata.get("service_line")),
                    subcategory=clean_text(metadata.get("subcategory")),
                    page_title=clean_text(metadata.get("page_title")),
                    document_summary=clean_text(metadata.get("document_summary")),
                    source_url=clean_text(metadata.get("source_url")),
                    source_path=str(path),
                    source_file=path.name,
                ),
            )
        return tuple(sorted(by_service_name.values(), key=lambda entry: entry.canonical_name))


class PostgresServiceRegistrySource:
    def __init__(self, dsn: str, table_name: str = SERVICE_REGISTRY_TABLE) -> None:
        self._dsn = dsn
        self._table_name = table_name

    def load_entries(self) -> tuple[ServiceRegistryEntry, ...]:
        query = f"""
            SELECT
                canonical_name,
                business_line,
                aliases,
                service_line,
                subcategory,
                page_title,
                document_summary,
                source_url,
                source_path,
                source_file
            FROM {self._table_name}
        """
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return tuple(_entry_from_record(row) for row in rows)


def get_service_registry_source() -> ServiceRegistrySource:
    dsn = _postgres_dsn()
    if SERVICE_REGISTRY_BACKEND == "auto":
        return PostgresServiceRegistrySource(dsn=dsn) if dsn else FilesServiceRegistrySource()
    if SERVICE_REGISTRY_BACKEND == "postgres":
        if not dsn:
            raise ValueError("OBJECTS_SERVICE_REGISTRY_BACKEND is postgres but no PostgreSQL DSN is configured.")
        return PostgresServiceRegistrySource(dsn=dsn)
    return FilesServiceRegistrySource()


@lru_cache(maxsize=1)
def load_service_registry() -> tuple[ServiceRegistryEntry, ...]:
    return get_service_registry_source().load_entries()


@lru_cache(maxsize=1)
def get_service_registry_payload() -> dict[str, Any]:
    entries = load_service_registry()
    by_canonical_name: dict[str, dict[str, Any]] = {}
    alias_to_services: dict[str, list[str]] = {}
    alias_to_match_records: dict[str, list[dict[str, str]]] = {}

    for entry in entries:
        payload = _entry_payload(entry)
        by_canonical_name[entry.canonical_name] = payload
        for alias_record in _alias_records_for_entry(entry):
            normalized = normalize_object_alias(alias_record.value)
            if not normalized:
                continue
            alias_to_services.setdefault(normalized, [])
            if entry.canonical_name not in alias_to_services[normalized]:
                alias_to_services[normalized].append(entry.canonical_name)
            alias_to_match_records.setdefault(normalized, [])
            alias_to_match_records[normalized].append(
                {
                    "canonical_name": entry.canonical_name,
                    "alias_value": alias_record.value,
                    "alias_kind": alias_record.alias_kind,
                    "business_line": entry.business_line,
                }
            )

    return {
        "entries": list(by_canonical_name.values()),
        "by_canonical_name": by_canonical_name,
        "alias_to_services": alias_to_services,
        "alias_to_match_records": alias_to_match_records,
    }


# Trailing-suffix patterns applied at lookup time when the parser's raw
# entity span doesn't match the alias index exactly.  The first seven
# mirror `_generate_service_phrase_variants` so lookup picks up the
# phrase variants the registry has ALREADY indexed at registration time
# (e.g. canonical "Rabbit Polyclonal Antibody Production" registers
# variant "Rabbit Polyclonal Antibody" by stripping "Production"; without
# symmetric strip at lookup, parser's "rabbit polyclonal antibody
# project" cannot reach it).  The last three are extras the parser
# emits in natural-language phrasing that registration does not generate
# from canonical names.
_LOOKUP_TRAIL_STRIP_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdesign and development\b$", ""),
    (r"\bservices\b$", ""),
    (r"\bservice\b$", ""),
    (r"\bdevelopment\b$", ""),
    (r"\bmanufacturing\b$", ""),
    (r"\bproduction\b$", ""),
    (r"\bassay\b$", ""),
    (r"\bproject\b$", ""),
    (r"\bprojects\b$", ""),
    (r"\bwork\b$", ""),
)


def _resolve_alias_lookup_key(alias: str) -> str:
    """Return an alias-index key that hits the registry, applying iterative
    trailing-suffix stripping when the raw input misses.

    Returns "" when no transformation produces a hit.

    Symmetry with registration: `_generate_service_phrase_variants`
    pre-generates phrase variants by stripping the same trailing
    suffixes from canonical names.  Without this lookup-side
    counterpart, parser-emitted phrases like "X service" / "X
    development" / "X project" would miss even though registration
    already indexed "X" as a phrase variant.
    """
    primary = normalize_object_alias(alias)
    if not primary:
        return ""
    payload = get_service_registry_payload()
    alias_index = payload["alias_to_services"]
    if primary in alias_index:
        return primary

    candidate = primary
    # Iteratively strip — multi-suffix shapes ("X development project")
    # need more than one pass.  Bounded by len(patterns) so it terminates.
    for _ in range(len(_LOOKUP_TRAIL_STRIP_PATTERNS)):
        progressed = False
        for pattern, replacement in _LOOKUP_TRAIL_STRIP_PATTERNS:
            stripped = re.sub(pattern, replacement, candidate, flags=re.IGNORECASE).strip()
            if not stripped or stripped == candidate:
                continue
            normalized = normalize_object_alias(stripped)
            if not normalized:
                continue
            # Single-token strips would otherwise produce overly generic
            # keys ("rabbit", "antibody") that could collide across
            # services.  Allow them ONLY when the stripped form is itself
            # a registered alias — acronyms ("CHO") and catalog-style
            # tokens that the alias map intentionally indexes as
            # multi-target ambiguity triggers.
            if len(normalized.split()) < 2 and normalized not in alias_index:
                continue
            candidate = normalized
            progressed = True
            if candidate in alias_index:
                return candidate
            break
        if not progressed:
            break
    return ""


def lookup_services_by_alias(alias: str) -> list[dict[str, Any]]:
    key = _resolve_alias_lookup_key(alias)
    if not key:
        return []
    payload = get_service_registry_payload()
    names = payload["alias_to_services"].get(key, [])
    return [
        payload["by_canonical_name"][name]
        for name in names
        if name in payload["by_canonical_name"]
    ]


def lookup_service_alias_matches(alias: str) -> list[dict[str, str]]:
    key = _resolve_alias_lookup_key(alias)
    if not key:
        return []
    payload = get_service_registry_payload()
    return payload["alias_to_match_records"].get(key, [])


def canonicalize_service_name(value: str) -> str:
    cleaned = clean_text(value)
    matches = lookup_services_by_alias(cleaned)
    canonical_names = {
        clean_text(match.get("canonical_name"))
        for match in matches
        if clean_text(match.get("canonical_name"))
    }
    if len(canonical_names) == 1:
        return next(iter(canonical_names))
    return cleaned


def _iter_service_page_files(source_dirs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for directory in source_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.txt")):
            if SERVICE_PAGE_FILE_PATTERN.search(path.name):
                paths.append(path)
    return paths


def _parse_document_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    start = text.find("[DOCUMENT]")
    end = text.find("[END_DOCUMENT]")
    if start == -1 or end == -1 or end <= start:
        return {}

    fields: dict[str, str] = {}
    block = text[start + len("[DOCUMENT]"):end]
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _KEY_VALUE_PATTERN.match(line)
        if not match:
            continue
        key = _normalize_key(match.group(1))
        value = clean_text(match.group(2))
        fields[key] = value
    return fields


def _normalize_key(raw_key: str) -> str:
    normalized = raw_key.strip().lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def _entry_payload(entry: ServiceRegistryEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["aliases"] = list(entry.aliases)
    payload["alias_records"] = [asdict(record) for record in _alias_records_for_entry(entry)]
    return payload


def _entry_from_record(record: dict[str, Any]) -> ServiceRegistryEntry:
    aliases = record.get("aliases", ())
    if isinstance(aliases, str):
        aliases = [clean_text(part) for part in aliases.replace(";", ",").split(",") if clean_text(part)]
    elif isinstance(aliases, list):
        aliases = [clean_text(alias) for alias in aliases if clean_text(alias)]
    return ServiceRegistryEntry(
        canonical_name=clean_text(record.get("canonical_name")),
        business_line=clean_text(record.get("business_line")),
        aliases=tuple(dedupe_preserve_order(list(aliases))),
        service_line=clean_text(record.get("service_line")),
        subcategory=clean_text(record.get("subcategory")),
        page_title=clean_text(record.get("page_title")),
        document_summary=clean_text(record.get("document_summary")),
        source_url=clean_text(record.get("source_url")),
        source_path=clean_text(record.get("source_path")),
        source_file=clean_text(record.get("source_file")),
    )


def _alias_records_for_entry(entry: ServiceRegistryEntry) -> list[ServiceAliasRecord]:
    records = _build_service_alias_records(
        entry.canonical_name,
        entry.page_title,
        entry.aliases,
    )
    return _dedupe_service_alias_records(records)


def _build_service_alias_records(
    canonical_name: str,
    page_title: str,
    aliases: tuple[str, ...],
) -> list[ServiceAliasRecord]:
    records: list[ServiceAliasRecord] = []
    canonical = clean_text(canonical_name)
    if canonical:
        records.append(ServiceAliasRecord(canonical, "canonical_name"))
        records.extend(_generate_service_phrase_variants(canonical))
        records.extend(_generate_service_abbreviation_variants(canonical))

    title = clean_text(page_title)
    if title and normalize_object_alias(title) != normalize_object_alias(canonical):
        records.append(ServiceAliasRecord(title, "page_title"))
        records.extend(_generate_service_phrase_variants(title, alias_kind="page_title_fragment"))
        records.extend(_generate_service_abbreviation_variants(title, alias_kind="abbreviation"))

    for alias in aliases:
        cleaned = clean_text(alias)
        if not cleaned or normalize_object_alias(cleaned) == normalize_object_alias(canonical):
            continue
        records.append(ServiceAliasRecord(cleaned, "synonym"))
        records.extend(_generate_service_abbreviation_variants(cleaned, alias_kind="abbreviation"))

    return records


def _generate_service_phrase_variants(text: str, alias_kind: str = "phrase_fragment") -> list[ServiceAliasRecord]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    variants: list[str] = []
    queue: list[str] = [cleaned]
    seen: set[str] = {normalize_object_alias(cleaned)}
    replacements = (
        (r"^custom\s+", ""),
        (r"\bdesign and development\b$", ""),
        (r"\bservices\b$", ""),
        (r"\bservice\b$", ""),
        (r"\bdevelopment\b$", ""),
        (r"\bmanufacturing\b$", ""),
        (r"\bproduction\b$", ""),
        (r"\bassay\b$", ""),
    )

    while queue:
        current = queue.pop(0)
        for pattern, replacement in replacements:
            candidate = clean_text(re.sub(pattern, replacement, current, flags=re.IGNORECASE))
            normalized = normalize_object_alias(candidate)
            if not candidate or normalized in seen:
                continue
            seen.add(normalized)
            if len(candidate.split()) >= 2:
                variants.append(candidate)
                queue.append(candidate)

    if cleaned.endswith(" Antibodies"):
        variants.append(cleaned[:-len("Antibodies")] + "Antibody")
    if cleaned.endswith(" Services"):
        variants.append(cleaned[:-len("Services")].strip())

    return [
        ServiceAliasRecord(value=variant, alias_kind=alias_kind)
        for variant in dedupe_preserve_order(variants)
        if normalize_object_alias(variant) != normalize_object_alias(cleaned)
    ]


def _generate_service_abbreviation_variants(text: str, alias_kind: str = "abbreviation") -> list[ServiceAliasRecord]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    variants: list[str] = []
    replacements = [
        ("mRNA-LNP", "mRNA LNP"),
        ("mRNA LNP", "mRNA-LNP"),
        ("mRNA-Lipid Nanoparticle", "mRNA-LNP"),
        ("mRNA Lipid Nanoparticle", "mRNA LNP"),
        ("mRNA-Lipid Nanoparticle", "mRNA LNP"),
        ("mRNA Lipid Nanoparticle", "mRNA-LNP"),
    ]
    for source, target in replacements:
        if source in cleaned:
            variants.append(cleaned.replace(source, target))

    return [
        ServiceAliasRecord(value=variant, alias_kind=alias_kind)
        for variant in dedupe_preserve_order(variants)
        if normalize_object_alias(variant) != normalize_object_alias(cleaned)
    ]


def _dedupe_service_alias_records(records: list[ServiceAliasRecord]) -> list[ServiceAliasRecord]:
    deduped: list[ServiceAliasRecord] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        normalized = normalize_object_alias(record.value)
        if not normalized:
            continue
        key = (normalized, record.alias_kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ServiceAliasRecord(clean_text(record.value), record.alias_kind))
    return deduped


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
