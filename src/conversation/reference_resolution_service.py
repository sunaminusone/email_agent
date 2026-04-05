import re

from src.schemas import ActiveEntityPayload, PersistedSessionPayload, ReferenceResolution, TurnResolution


REFERENTIAL_PATTERNS = {
    "active": (
        "this one",
        "that one",
        "this product",
        "that product",
        "this service",
        "that service",
        "same one",
        "same product",
        "same service",
        "it",
        "its",
        "it's",
    ),
    "other": (
        "the other one",
        "the other product",
        "the other service",
        "another one",
        "another product",
        "another service",
    ),
    "first": (
        "the first one",
        "first one",
        "the first product",
        "the first service",
    ),
    "second": (
        "the second one",
        "second one",
        "the second product",
        "the second service",
    ),
    "previous": (
        "the previous one",
        "the previous product",
        "the previous service",
        "previous one",
        "last one",
    ),
    "all": (
        "both of them",
        "all of them",
        "both products",
        "both services",
        "the two of them",
        "those two",
    ),
}


def _normalize_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = lowered.replace("_", " ").replace("-", " ")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _entity_is_usable(entity: ActiveEntityPayload) -> bool:
    return bool(entity.identifier or entity.display_name or entity.business_line)


def _entity_matches_query(entity: ActiveEntityPayload, normalized_query: str) -> bool:
    candidates = [
        entity.identifier,
        entity.identifier_type,
        entity.display_name,
        entity.business_line,
        entity.entity_kind,
    ]
    normalized_candidates = [_normalize_text(value) for value in candidates if value]
    return any(candidate and candidate in normalized_query for candidate in normalized_candidates)


def _choose_other_entity(session_payload: PersistedSessionPayload) -> ActiveEntityPayload:
    active = session_payload.active_entity
    for entity in session_payload.recent_entities:
        if not _entity_is_usable(entity):
            continue
        if entity.identifier and entity.identifier == active.identifier:
            continue
        if entity.display_name and entity.display_name == active.display_name:
            continue
        return entity
    return ActiveEntityPayload()


def _choose_index_entity(session_payload: PersistedSessionPayload, index: int) -> ActiveEntityPayload:
    entities = [entity for entity in session_payload.recent_entities if _entity_is_usable(entity)]
    if 0 <= index < len(entities):
        return entities[index]
    return ActiveEntityPayload()


def _resolution_from_entity(entity: ActiveEntityPayload, mode: str, confidence: float, reason: str) -> ReferenceResolution:
    if not _entity_is_usable(entity):
        return ReferenceResolution()
    return ReferenceResolution(
        resolved_identifier=entity.identifier,
        resolved_identifiers=[entity.identifier] if entity.identifier else [],
        resolved_identifier_type=entity.identifier_type,
        resolved_display_name=entity.display_name,
        resolved_business_line=entity.business_line,
        resolution_mode=mode,
        confidence=confidence,
        reason=reason,
    )


def _choose_all_entities(session_payload: PersistedSessionPayload) -> list[ActiveEntityPayload]:
    entities: list[ActiveEntityPayload] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entity in session_payload.recent_entities:
        if not _entity_is_usable(entity):
            continue
        signature = (
            entity.identifier.strip().lower(),
            entity.identifier_type.strip().lower(),
            entity.display_name.strip().lower(),
            entity.business_line.strip().lower(),
        )
        if signature in seen:
            continue
        seen.add(signature)
        entities.append(entity)
    return entities


def _resolution_from_entities(entities: list[ActiveEntityPayload], mode: str, confidence: float, reason: str) -> ReferenceResolution:
    usable = [entity for entity in entities if _entity_is_usable(entity)]
    if not usable:
        return ReferenceResolution()
    primary = usable[0]
    identifiers = [entity.identifier for entity in usable if entity.identifier]
    return ReferenceResolution(
        resolved_identifier=primary.identifier,
        resolved_identifiers=identifiers,
        resolved_identifier_type=primary.identifier_type,
        resolved_display_name=primary.display_name,
        resolved_business_line=primary.business_line,
        resolution_mode=mode,
        confidence=confidence,
        reason=reason,
    )


def resolve_reference(
    query: str,
    turn_resolution: TurnResolution,
    session_payload: PersistedSessionPayload,
) -> ReferenceResolution:
    normalized_query = _normalize_text(query)
    active_entity = session_payload.active_entity

    if any(pattern in normalized_query for pattern in REFERENTIAL_PATTERNS["other"]):
        return _resolution_from_entity(
            _choose_other_entity(session_payload),
            "other_recent_entity",
            0.78,
            "The query refers to another recent entity, so the resolver selected the nearest non-active entity.",
        )

    if any(pattern in normalized_query for pattern in REFERENTIAL_PATTERNS["all"]):
        return _resolution_from_entities(
            _choose_all_entities(session_payload),
            "all_recent_entities",
            0.8,
            "The query refers to all recently discussed entities.",
        )

    if any(pattern in normalized_query for pattern in REFERENTIAL_PATTERNS["first"]):
        return _resolution_from_entity(
            _choose_index_entity(session_payload, 0),
            "indexed_recent_entity",
            0.76,
            "The query refers to the first recent entity.",
        )

    if any(pattern in normalized_query for pattern in REFERENTIAL_PATTERNS["second"]):
        return _resolution_from_entity(
            _choose_index_entity(session_payload, 1),
            "indexed_recent_entity",
            0.74,
            "The query refers to the second recent entity.",
        )

    if any(pattern in normalized_query for pattern in REFERENTIAL_PATTERNS["previous"]):
        return _resolution_from_entity(
            _choose_other_entity(session_payload),
            "previous_recent_entity",
            0.73,
            "The query refers to the previously discussed entity.",
        )

    if turn_resolution.payload_usable and turn_resolution.resolved_identifier:
        return ReferenceResolution(
            resolved_identifier=turn_resolution.resolved_identifier,
            resolved_identifiers=[turn_resolution.resolved_identifier],
            resolved_identifier_type=turn_resolution.resolved_identifier_type,
            resolved_display_name=active_entity.display_name,
            resolved_business_line=turn_resolution.resolved_business_line or session_payload.active_business_line,
            resolution_mode="turn_resolution",
            confidence=turn_resolution.confidence,
            reason=turn_resolution.reason,
        )

    if turn_resolution.should_reuse_active_entity and _entity_is_usable(active_entity):
        return _resolution_from_entity(
            active_entity,
            "active_entity",
            max(turn_resolution.confidence, 0.75),
            "The active entity can be reused for this follow-up turn.",
        )

    for entity in [active_entity, *session_payload.recent_entities]:
        if _entity_matches_query(entity, normalized_query):
            return _resolution_from_entity(
                entity,
                "entity_text_match",
                0.8,
                "The query explicitly matches a recent entity by identifier, display name, or business line.",
            )

    return ReferenceResolution()
