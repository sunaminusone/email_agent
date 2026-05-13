from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from src.config.settings import get_llm
from src.memory.models import MemoryContext
from src.ingestion.models import ParserRequestFlags, ParserSignals
from src.routing.models import RoutedObjectState
from src.routing.models import DialogueActResult


class _DialogueActLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    act: str = "inquiry"
    is_continuation: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


# Intents that indicate the user has no active request — pure
# conversational closing or acknowledgement.
_CLOSING_INTENTS: frozenset[str] = frozenset({"unknown"})

# Intents where the user is continuing / following up on prior context.
_CONTINUATION_INTENTS: frozenset[str] = frozenset({"follow_up"})

_TERMINATION_PATTERNS: tuple[str, ...] = (
    "bye",
    "goodbye",
    "stop",
    "no thanks",
    "no thank you",
    "结束",
    "不用了",
    "先这样",
)
_ACKNOWLEDGEMENT_EN_RE = re.compile(
    r"\b(?:thanks|thank you|got it|sounds good|perfect|sure|ok|okay)\b",
    re.IGNORECASE,
)
_ACKNOWLEDGEMENT_ZH: tuple[str, ...] = ("明白了", "好的", "收到", "谢谢")
_ACK_SHORT_MAX_TOKENS = 6


def _looks_like_acknowledgement(text: str) -> bool:
    """ACK only fires on short messages — long emails that politely end
    with 'Thank you' must not be mis-classified as closing."""
    if not text:
        return False
    if len(text.split()) > _ACK_SHORT_MAX_TOKENS:
        return False
    if _ACKNOWLEDGEMENT_EN_RE.search(text):
        return True
    return _matches_any(text, _ACKNOWLEDGEMENT_ZH)
_SELECTION_PATTERNS: tuple[str, ...] = (
    "the first one",
    "first one",
    "the second one",
    "second one",
    "the third one",
    "third one",
    "the other one",
    "another one",
    "this one",
    "that one",
    "i'll take that",
    "i will take that",
    "option 1",
    "option 2",
    "option 3",
    "第一个",
    "第二个",
    "第三个",
    "这个",
    "那个",
)
_ELABORATION_PATTERNS: tuple[str, ...] = (
    "tell me more",
    "more about",
    "continue",
    "go on",
    "and the pricing",
    "what else",
    "还有",
    "继续",
    "再说说",
    "多说一点",
)
_SELECTION_SHORT_MAX_TOKENS = 8
_INQUIRY_MARKERS: tuple[str, ...] = (
    "?",
    "what",
    "how",
    "why",
    "when",
    "which",
    "price",
    "pricing",
    "quote",
    "protocol",
    "status",
    "can you",
    "could you",
    "多少钱",
    "什么",
    "怎么",
    "为什么",
)


# ---------------------------------------------------------------------------
# v3: signal-driven 3-act classification
# ---------------------------------------------------------------------------

def resolve_dialogue_act(
    query: str,
    parser_signals: ParserSignals,
    object_routing: RoutedObjectState,
    *,
    memory_context: MemoryContext | None = None,
) -> DialogueActResult:
    """Classify the turn into one of three dialogue acts based on parser signals.

    The parser LLM has already extracted intent, entities, flags, and
    selection resolution.  This function makes a routing *decision* from
    those signals — it never re-interprets raw query text.
    """
    text = _normalize_text(query)
    selection = parser_signals.selection_resolution
    context = parser_signals.context
    intent = context.semantic_intent
    hint = context.dialogue_act_hint
    pending_clarification = bool(
        memory_context is not None
        and memory_context.snapshot.clarification_memory.pending_clarification_type
    )

    # ---- selection (parser-resolved from pending options) -----------------
    if selection is not None and selection.selection_confidence >= 0.5:
        return DialogueActResult(
            act="selection",
            confidence=selection.selection_confidence,
            reason="Parser resolved a user selection from pending clarification.",
            matched_signals=["parser_selection_resolution"],
            requires_active_object=True,
            selection_value=selection.selected_value,
        )

    # ---- selection (cold-start hint from query text) ----------------------
    if hint == "selection":
        return DialogueActResult(
            act="selection",
            confidence=max(context.intent_confidence, 0.70),
            reason="Parser hint: cold-start selection commitment without pending options.",
            matched_signals=["parser_dialogue_act_hint"],
            requires_active_object=True,
        )

    # ---- closing (cold-start hint from query text) ------------------------
    if hint == "closing":
        return DialogueActResult(
            act="closing",
            confidence=max(context.intent_confidence, 0.70),
            reason="Parser hint: pure acknowledgement / conversational closing.",
            matched_signals=["parser_dialogue_act_hint"],
        )

    # ---- selection (memory-aware post-clarification fallback) -------------
    if pending_clarification and _looks_like_selection_reply(text):
        return DialogueActResult(
            act="selection",
            confidence=max(context.intent_confidence, 0.85),
            reason="Pending clarification context plus a short selection-style reply indicate option selection.",
            matched_signals=["pending_clarification", "selection_pattern"],
            requires_active_object=object_routing.active_object is not None,
            selection_value=query.strip(),
        )

    # ---- LLM fallback for ambiguous / low-confidence queries --------------
    # Runs before lexical close/sel/ack and _is_closing so weak lexical
    # patterns ("这个", short non-English) can't pre-empt a richer LLM read.
    fallback_attempted = False
    if _should_use_llm_fallback(text, parser_signals):
        fallback_attempted = True
        fallback = _llm_classify_dialogue_act(
            query=query,
            object_routing=object_routing,
            memory_context=memory_context,
        )
        if fallback is not None:
            return fallback

    # ---- closing (intent=unknown, no flags) -------------------------------
    # Above the lexical TERMINATION block so "bye" + parser unknown is
    # attributed to the parser decision rather than the surface pattern.
    if not fallback_attempted and _is_closing(intent, context.intent_confidence, parser_signals.request_flags):
        return DialogueActResult(
            act="closing",
            confidence=max(0.80, 1.0 - context.intent_confidence),
            reason="No active customer intent detected; treating as conversational closing.",
            matched_signals=["parser_no_active_intent"],
        )

    # ---- closing / selection lexical fallbacks ----------------------------
    if not fallback_attempted and _matches_any(text, _TERMINATION_PATTERNS):
        return DialogueActResult(
            act="closing",
            confidence=max(context.intent_confidence, 0.85),
            reason="Explicit stop or closure signal.",
            matched_signals=["terminate_pattern"],
        )

    if not fallback_attempted and _looks_like_selection_reply(text):
        return DialogueActResult(
            act="selection",
            confidence=max(context.intent_confidence, 0.75),
            reason="Selection-style reply detected from the message text.",
            matched_signals=["selection_pattern"],
            requires_active_object=True,
            selection_value=query.strip(),
        )

    if not fallback_attempted and _looks_like_acknowledgement(text):
        return DialogueActResult(
            act="closing",
            confidence=max(context.intent_confidence, 0.75),
            reason="Acknowledgement or conversational closing signal detected.",
            matched_signals=["acknowledgement_pattern"],
        )

    # ---- inquiry (strong deterministic inquiry markers) -------------------
    if _looks_like_inquiry(text, parser_signals):
        is_continuation = intent in _CONTINUATION_INTENTS or _matches_any(text, _ELABORATION_PATTERNS)
        return DialogueActResult(
            act="inquiry",
            is_continuation=is_continuation,
            confidence=max(context.intent_confidence, 0.75),
            reason=(
                "Continuation of prior context."
                if is_continuation
                else "Inquiry markers or strong parser signals indicate an active request."
            ),
            matched_signals=["parser_follow_up"] if is_continuation else ["inquiry_pattern"],
        )

    # ---- inquiry (default) ------------------------------------------------
    is_continuation = intent in _CONTINUATION_INTENTS or _matches_any(text, _ELABORATION_PATTERNS)
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


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _looks_like_selection_reply(text: str) -> bool:
    """Selection only fires on short replies — long emails containing
    'the other one' as part of a question must not be mis-classified."""
    if not text:
        return False
    if text in {"sure", "yes", "yep", "okay", "ok", "好的", "行", "可以"}:
        return True
    if len(text.split()) > _SELECTION_SHORT_MAX_TOKENS:
        return False
    return _matches_any(text, _SELECTION_PATTERNS)


def _looks_like_inquiry(text: str, parser_signals: ParserSignals) -> bool:
    if not text:
        return False
    if _matches_any(text, _ELABORATION_PATTERNS):
        return True
    if any(marker in text for marker in _INQUIRY_MARKERS):
        return True
    context = parser_signals.context
    return (
        context.intent_confidence >= 0.8
        and context.semantic_intent not in {"unknown", "general_info"}
    )


def _should_use_llm_fallback(text: str, parser_signals: ParserSignals) -> bool:
    if not text:
        return False
    context = parser_signals.context
    token_count = len(text.split())
    contains_non_ascii = any(ord(ch) > 127 for ch in text)
    has_inquiry_markers = any(marker in text for marker in _INQUIRY_MARKERS)
    if not has_inquiry_markers and (
        _matches_any(text, _TERMINATION_PATTERNS)
        or _looks_like_acknowledgement(text)
    ):
        return False
    mixed_posture = (
        _looks_like_acknowledgement(text)
        and any(marker in text for marker in ("?", "what", "how", "price", "pricing", "why", "多少钱"))
    )
    short_ambiguous = (
        token_count <= 4
        and not has_inquiry_markers
        and context.semantic_intent in {"unknown", "general_info", "follow_up"}
    )
    weak_non_english = (
        contains_non_ascii
        and not has_inquiry_markers
        and context.intent_confidence < 0.6
    )
    low_confidence_follow_up = (
        context.semantic_intent == "follow_up"
        and context.intent_confidence < 0.6
        and token_count <= 6
        and not has_inquiry_markers
    )
    return any([mixed_posture, short_ambiguous, weak_non_english, low_confidence_follow_up])


def _llm_classify_dialogue_act(
    *,
    query: str,
    object_routing: RoutedObjectState,
    memory_context: MemoryContext | None = None,
) -> DialogueActResult | None:
    active_route = memory_context.active_route if memory_context is not None else ""
    clarification_type = (
        memory_context.snapshot.clarification_memory.pending_clarification_type
        if memory_context is not None
        else ""
    )
    primary_object = (
        object_routing.primary_object.display_name
        or object_routing.primary_object.identifier
        or object_routing.primary_object.canonical_value
        if object_routing.primary_object is not None
        else ""
    )

    prompt = (
        "You are classifying a support-copilot user message.\n\n"
        f"Customer message: {query!r}\n"
        f"Resolved entity: {primary_object or 'none'}\n"
        f"Conversation state: {active_route or 'new'}\n"
        f"Pending clarification: {clarification_type or 'none'}\n\n"
        "Classify the message into exactly one act:\n"
        "- inquiry: asking for information or requesting an action\n"
        "- selection: choosing from previously offered options\n"
        "- closing: confirming, thanking, or ending the conversation\n\n"
        "Rules:\n"
        "- Use selection only when the message clearly chooses or commits to a previously discussed option.\n"
        "- Generic acknowledgements like 'sure', 'ok', or 'sounds good' are closing unless there is a pending clarification.\n"
        "- If the message asks for new information, treat it as inquiry even if it begins with 'ok' or 'thanks'.\n"
        "- Be conservative: if unsure between inquiry and closing, prefer inquiry. If unsure between selection and closing without pending clarification, prefer closing.\n\n"
        "Also determine whether this continues the prior topic.\n"
        "Return structured output only."
    )

    try:
        llm = get_llm().with_structured_output(_DialogueActLLMOutput)
        result = llm.invoke(prompt)
    except Exception:
        return None

    act = result.act if result.act in {"inquiry", "selection", "closing"} else "inquiry"
    confidence = min(max(float(result.confidence or 0.0), 0.0), 1.0)
    return DialogueActResult(
        act=act,
        is_continuation=bool(result.is_continuation),
        confidence=confidence,
        reason=result.reason or "LLM fallback classified the dialogue act.",
        matched_signals=["llm_fallback"],
        requires_active_object=(act == "selection"),
        selection_value=query.strip() if act == "selection" else "",
    )
