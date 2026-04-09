from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.rag.service_page_ingestion import load_service_page_documents


@dataclass(frozen=True)
class ServiceRegistryEntry:
    canonical_name: str
    business_line: str
    aliases: tuple[str, ...] = ()
    source_path: str = ""


MANUAL_SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "mRNA-LNP Gene Delivery": (
        "mRNA LNP Gene Delivery",
        "mRNA-LNP delivery",
        "mRNA LNP delivery",
        "LNP gene delivery",
        "mRNA Lipid Nanoparticle Gene Delivery",
    ),
    "Mouse Monoclonal Antibodies": (
        "Mouse Monoclonal Antibody Service",
        "Mouse Monoclonal Antibody Development",
    ),
    "Rabbit Monoclonal Antibodies": (
        "Rabbit Monoclonal Antibody Service",
        "Rabbit Monoclonal Antibody Development",
    ),
    "Rabbit Polyclonal Antibody Production": (
        "Rabbit Polyclonal Antibodies",
        "Rabbit Polyclonal Antibody Service",
    ),
    "CAR-T Cell Design and Development": (
        "Custom CAR-T Cell Development",
        "CAR-T Development",
    ),
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_text(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


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


@lru_cache(maxsize=1)
def load_service_registry() -> tuple[ServiceRegistryEntry, ...]:
    by_service_name: dict[str, dict[str, str]] = {}
    for document in load_service_page_documents():
        metadata = dict(document.metadata)
        service_name = _clean_text(metadata.get("service_name"))
        business_line = _clean_text(metadata.get("business_line"))
        source_path = _clean_text(metadata.get("source_path"))
        if not service_name:
            continue
        by_service_name.setdefault(
            service_name,
            {
                "business_line": business_line,
                "source_path": source_path,
            },
        )

    entries: list[ServiceRegistryEntry] = []
    for canonical_name, metadata in sorted(by_service_name.items()):
        aliases = _dedupe_aliases(
            [
                canonical_name,
                *(MANUAL_SERVICE_ALIASES.get(canonical_name, ())),
            ]
        )
        entries.append(
            ServiceRegistryEntry(
                canonical_name=canonical_name,
                business_line=metadata.get("business_line", ""),
                aliases=aliases,
                source_path=metadata.get("source_path", ""),
            )
        )
    return tuple(entries)


@lru_cache(maxsize=1)
def get_service_registry_payload() -> dict[str, Any]:
    entries = load_service_registry()

    by_canonical_name: dict[str, dict[str, Any]] = {}
    alias_to_services: dict[str, list[str]] = {}
    for entry in entries:
        by_canonical_name[entry.canonical_name] = {
            "canonical_name": entry.canonical_name,
            "business_line": entry.business_line,
            "aliases": list(entry.aliases),
            "source_path": entry.source_path,
        }
        for alias in entry.aliases:
            normalized = _normalize_text(alias)
            if not normalized:
                continue
            services = alias_to_services.setdefault(normalized, [])
            if entry.canonical_name not in services:
                services.append(entry.canonical_name)

    return {
        "entries": list(by_canonical_name.values()),
        "by_canonical_name": by_canonical_name,
        "alias_to_services": alias_to_services,
    }


def lookup_services_by_alias(alias: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(alias)
    if not normalized:
        return []

    payload = get_service_registry_payload()
    names = payload["alias_to_services"].get(normalized, [])
    return [
        payload["by_canonical_name"][name]
        for name in names
        if name in payload["by_canonical_name"]
    ]


def canonicalize_service_name(value: str) -> str:
    cleaned = _clean_text(value)
    matches = lookup_services_by_alias(cleaned)
    canonical_names = {
        _clean_text(match.get("canonical_name"))
        for match in matches
        if _clean_text(match.get("canonical_name"))
    }
    if len(canonical_names) == 1:
        return next(iter(canonical_names))
    return cleaned


__all__ = [
    "MANUAL_SERVICE_ALIASES",
    "ServiceRegistryEntry",
    "canonicalize_service_name",
    "get_service_registry_payload",
    "load_service_registry",
    "lookup_services_by_alias",
]
