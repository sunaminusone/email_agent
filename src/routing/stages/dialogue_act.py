from __future__ import annotations

import re

from src.routing.models import DialogueActResult, RoutedObjectState
from src.routing.utils import normalize_routing_text


TERMINATE_PATTERNS = {
    "stop",
    "cancel",
    "never mind",
    "nevermind",
    "no thanks",
    "no thank you",
    "bye",
    "goodbye",
}
ACKNOWLEDGE_PATTERNS = {
    "thanks",
    "thank you",
    "got it",
    "ok",
    "okay",
    "understood",
    "received",
}
ELABORATE_PATTERNS = {
    "tell me more",
    "more detail",
    "more details",
    "explain more",
    "expand on",
    "go deeper",
    "elaborate",
}
SELECTION_PREFIXES = {
    "select ",
    "choose ",
    "pick ",
    "the first",
    "the second",
    "option ",
    "number ",
}


def resolve_dialogue_act(query: str, object_routing: RoutedObjectState) -> DialogueActResult:
    text = normalize_routing_text(query or "").strip()
    if not text:
        return DialogueActResult(reason="The turn did not contain enough text to classify a dialogue act.")

    if any(pattern in text for pattern in TERMINATE_PATTERNS):
        return DialogueActResult(
            act="TERMINATE",
            confidence=0.92,
            reason="The turn contains an explicit stop or closure signal.",
            matched_signals=["terminate_pattern"],
        )

    if _looks_like_selection(text, object_routing):
        return DialogueActResult(
            act="SELECTION",
            confidence=0.88,
            reason="The turn appears to select one candidate from prior context.",
            matched_signals=["selection_pattern"],
            requires_active_object=True,
            selection_value=query.strip(),
        )

    if any(pattern in text for pattern in ELABORATE_PATTERNS):
        return DialogueActResult(
            act="ELABORATE",
            confidence=0.82,
            reason="The turn asks for expansion or deeper explanation.",
            matched_signals=["elaboration_pattern"],
            requires_active_object=object_routing.active_object is not None,
        )

    if _looks_like_acknowledgement(text):
        return DialogueActResult(
            act="ACKNOWLEDGE",
            confidence=0.81,
            reason="The turn mainly acknowledges the prior response.",
            matched_signals=["acknowledgement_pattern"],
        )

    if _looks_like_inquiry(text):
        return DialogueActResult(
            act="INQUIRY",
            confidence=0.84,
            reason="The turn asks for information or action-oriented detail.",
            matched_signals=["inquiry_pattern"],
        )

    return DialogueActResult(
        act="UNKNOWN",
        confidence=0.35,
        reason="The turn did not strongly match the current dialogue-act heuristics.",
    )


def _looks_like_selection(text: str, object_routing: RoutedObjectState) -> bool:
    if re.fullmatch(r"\d+", text):
        return True
    if any(text.startswith(prefix) for prefix in SELECTION_PREFIXES):
        return True
    if text in {"first", "second", "third", "1", "2", "3"}:
        return True

    candidate_names = [
        candidate.display_name.lower()
        for ambiguous_set in object_routing.ambiguous_objects
        for candidate in ambiguous_set.candidate_refs
        if candidate.display_name
    ]
    return any(name and name in text for name in candidate_names)


def _looks_like_acknowledgement(text: str) -> bool:
    if "?" in text:
        return False
    return any(pattern in text for pattern in ACKNOWLEDGE_PATTERNS)


def _looks_like_inquiry(text: str) -> bool:
    inquiry_markers = {"?", "what", "how", "why", "which", "when", "where", "can you", "could you"}
    return any(marker in text for marker in inquiry_markers)
