from __future__ import annotations

from typing import Any

from src.ingestion.deterministic_signals import extract_deterministic_signals
from src.ingestion.models import IngestionBundle, TurnSignals
from src.ingestion.normalizers import normalize_turn_inputs
from src.ingestion.parser_adapter import build_parser_signals
from src.ingestion.reference_signals import extract_reference_signals
from src.ingestion.signal_refinement import refine_parser_signals
from src.ingestion.stateful_anchors import extract_stateful_anchors
from src.memory.models import StatefulAnchors


def build_ingestion_bundle(
    *,
    thread_id: str | None,
    user_query: str,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    prior_state: Any | None = None,
    stateful_anchors: StatefulAnchors | None = None,
    has_recent_objects: bool = False,
) -> IngestionBundle:
    turn_core, normalized_history, attachment_signals = normalize_turn_inputs(
        thread_id=thread_id,
        raw_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    parser_signals = build_parser_signals(
        user_query=turn_core.normalized_query,
        conversation_history=normalized_history,
        attachments=attachments,
    )
    parser_signals = refine_parser_signals(
        parser_signals,
        normalized_query=turn_core.normalized_query,
        attachment_signals=attachment_signals,
    )

    turn_core = turn_core.model_copy(
        update={
            "language": str(parser_signals.context.language or turn_core.language),
            "channel": str(parser_signals.context.channel or turn_core.channel),
        }
    )

    if stateful_anchors is None:
        stateful_anchors = extract_stateful_anchors(prior_state)
    deterministic_signals = extract_deterministic_signals(
        turn_core.normalized_query,
        parser_signals=parser_signals,
    )
    reference_signals = extract_reference_signals(
        turn_core.normalized_query,
        parser_signals=parser_signals,
        stateful_anchors=stateful_anchors,
        has_recent_objects=has_recent_objects,
    )

    return IngestionBundle(
        turn_core=turn_core,
        turn_signals=TurnSignals(
            parser_signals=parser_signals,
            deterministic_signals=deterministic_signals,
            reference_signals=reference_signals,
            attachment_signals=attachment_signals,
        ),
        stateful_anchors=stateful_anchors,
    )
