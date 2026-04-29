from __future__ import annotations

from typing import Any

from src.ingestion.deterministic_signals import extract_deterministic_signals
from src.ingestion.entity_to_constraint import entities_to_attribute_constraints
from src.ingestion.models import IngestionBundle, TurnSignals
from src.ingestion.normalizers import normalize_turn_inputs
from src.ingestion.parser_adapter import build_parser_signals
from src.ingestion.reference_signals import extract_reference_signals
from src.ingestion.signal_refinement import refine_parser_signals
from src.memory import recall
from src.memory.models import MemoryContext


def build_ingestion_bundle(
    *,
    thread_id: str | None,
    user_query: str,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    memory_context: MemoryContext | None = None,
    prior_state: Any | None = None,
) -> IngestionBundle:
    turn_core, normalized_history, attachment_signals = normalize_turn_inputs(
        thread_id=thread_id,
        raw_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    if memory_context is None:
        memory_context = recall(
            thread_id=thread_id or "",
            user_query=turn_core.normalized_query or user_query,
            prior_state=prior_state,
        )

    parser_signals, llm_normalized = build_parser_signals(
        user_query=turn_core.normalized_query,
        conversation_history=normalized_history,
        attachments=attachments,
        memory_context=memory_context,
    )
    deterministic_signals = extract_deterministic_signals(
        turn_core.normalized_query,
        parser_signals=parser_signals,
    )
    parser_signals = refine_parser_signals(
        parser_signals,
        normalized_query=turn_core.normalized_query,
        attachment_signals=attachment_signals,
    )

    turn_core = turn_core.model_copy(
        update={
            "normalized_query": llm_normalized or turn_core.normalized_query,
            "language": str(parser_signals.context.language or turn_core.language),
            "channel": str(parser_signals.context.channel or turn_core.channel),
        }
    )
    reference_signals = extract_reference_signals(
        turn_core.normalized_query,
        parser_signals=parser_signals,
        memory_context=memory_context,
    )

    bridged_constraints = entities_to_attribute_constraints(parser_signals.entities)
    if bridged_constraints:
        existing = list(reference_signals.attribute_constraints)
        seen = {(c.attribute, c.value) for c in existing}
        for constraint in bridged_constraints:
            key = (constraint.attribute, constraint.value)
            if key in seen:
                continue
            existing.append(constraint)
            seen.add(key)
        reference_signals = reference_signals.model_copy(update={"attribute_constraints": existing})

    return IngestionBundle(
        turn_core=turn_core,
        turn_signals=TurnSignals(
            parser_signals=parser_signals,
            deterministic_signals=deterministic_signals,
            reference_signals=reference_signals,
            attachment_signals=attachment_signals,
        ),
        memory_context=memory_context,
    )
