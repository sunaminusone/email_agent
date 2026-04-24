from __future__ import annotations

from src.ingestion.models import ParserRequestFlags, ParserSignals
from src.routing.models import DialogueActResult


# Intents that indicate the user has no active request — pure
# conversational closing or acknowledgement.
_CLOSING_INTENTS: frozenset[str] = frozenset({"unknown"})

# Intents where the user is continuing / following up on prior context.
_CONTINUATION_INTENTS: frozenset[str] = frozenset({"follow_up"})


# ---------------------------------------------------------------------------
# v3: signal-driven 3-act classification
# ---------------------------------------------------------------------------

def resolve_dialogue_act(
    parser_signals: ParserSignals,
    *,
    stateful_anchors=None,
) -> DialogueActResult:
    """Classify the turn into one of three dialogue acts based on parser signals.

    The parser LLM has already extracted intent, entities, flags, and
    selection resolution.  This function makes a routing *decision* from
    those signals — it never re-interprets raw query text.
    """
    selection = parser_signals.selection_resolution
    context = parser_signals.context
    intent = context.semantic_intent

    # ---- selection --------------------------------------------------------
    if selection is not None and selection.selection_confidence >= 0.5:
        return DialogueActResult(
            act="selection",
            confidence=selection.selection_confidence,
            reason="Parser resolved a user selection from pending clarification.",
            matched_signals=["parser_selection_resolution"],
            requires_active_object=True,
            selection_value=selection.selected_value,
        )

    # ---- closing ----------------------------------------------------------
    if _is_closing(intent, context.intent_confidence, parser_signals.request_flags):
        return DialogueActResult(
            act="closing",
            confidence=max(0.80, 1.0 - context.intent_confidence),
            reason="No active customer intent detected; treating as conversational closing.",
            matched_signals=["parser_no_active_intent"],
        )

    # ---- inquiry (default) ------------------------------------------------
    is_continuation = intent in _CONTINUATION_INTENTS
    return DialogueActResult(
        act="inquiry",
        is_continuation=is_continuation,
        confidence=max(context.intent_confidence, 0.70),
        reason=(
            "Continuation of prior context."
            if is_continuation
            else "Active customer intent detected."
        ),
        matched_signals=["parser_follow_up"] if is_continuation else ["parser_intent"],
    )


def _is_closing(intent: str, intent_confidence: float, flags: ParserRequestFlags) -> bool:
    """Determine if the turn is a closing signal based on parser output.

    Closing = the parser found no meaningful customer intent.  This is
    signalled by an 'unknown' semantic_intent with low confidence AND no
    request flags set.
    """
    if intent not in _CLOSING_INTENTS:
        return False
    if intent_confidence > 0.5:
        return False
    if _has_any_request_flags(flags):
        return False
    return True


def _has_any_request_flags(flags: ParserRequestFlags) -> bool:
    return any(getattr(flags, field) for field in ParserRequestFlags.model_fields)
