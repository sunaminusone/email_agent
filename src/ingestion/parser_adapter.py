from __future__ import annotations

import json
from typing import Any, Mapping

from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from src.config.settings import get_llm
from src.ingestion.models import (
    EntitySpan,
    ParserConstraints,
    ParserContext,
    ParserEntitySignals,
    ParserEntityOutputSpan,
    ParserOpenSlots,
    ParserOutput,
    ParserRetrievalHints,
    ParserRequestFlags,
    ParserSignals,
    SelectionResolution,
    SourceAttribution,
)
from src.ingestion.parser_prompt import get_parser_prompt
from src.memory.models import StatefulAnchors


def _format_pending_clarification(stateful_anchors: StatefulAnchors | None) -> str:
    """Format pending clarification context for the parser prompt."""
    if stateful_anchors is None or not stateful_anchors.pending_clarification_field:
        return "None"
    options = stateful_anchors.pending_candidate_options
    if not options:
        return "None"
    # 1-based labels match the user's mental model (assistant turns
    # typically present options as "1) X 2) Y 3) Z").  The schema's
    # selected_index remains 0-based; the parser_prompt rule + the
    # 第二个 / "the first one" few-shots cover the 1→0 translation.
    lines = [f"Type: {stateful_anchors.pending_clarification_field}", "Options:"]
    for idx, option in enumerate(options, start=1):
        lines.append(f"  {idx}: {option}")
    return "\n".join(lines)


def preprocess_for_parser(
    *,
    user_query: str,
    conversation_history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    stateful_anchors: StatefulAnchors | None = None,
) -> dict[str, Any]:
    normalized_query = str(user_query or "").strip()
    normalized_history = conversation_history or []
    normalized_attachments = attachments or []
    return {
        "user_query": normalized_query,
        "conversation_history": json.dumps(
            normalized_history,
            ensure_ascii=False,
            indent=2,
        ),
        "attachments": json.dumps(
            normalized_attachments,
            ensure_ascii=False,
            indent=2,
        ),
        "pending_clarification": _format_pending_clarification(stateful_anchors),
        "_meta": {
            "raw_user_query": normalized_query,
            "conversation_history_raw": normalized_history,
            "attachments_raw": normalized_attachments,
        },
    }


def get_parser_pipeline():
    llm = get_llm()
    structured_llm = llm.with_structured_output(ParserOutput)
    parser_prompt = get_parser_prompt()
    parser_chain = parser_prompt | structured_llm

    preprocess = RunnableLambda(
        lambda payload: preprocess_for_parser(
            user_query=payload.get("user_query", ""),
            conversation_history=payload.get("conversation_history", []),
            attachments=payload.get("attachments", []),
            stateful_anchors=payload.get("stateful_anchors"),
        )
    )
    parse_step = RunnablePassthrough.assign(parsed=parser_chain)
    unwrap = RunnableLambda(lambda payload: payload["parsed"])
    return preprocess | parse_step | unwrap


def invoke_parser_pipeline(
    *,
    user_query: str,
    conversation_history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    stateful_anchors: StatefulAnchors | None = None,
) -> dict[str, Any]:
    pipeline = get_parser_pipeline()
    parsed = pipeline.invoke(
        {
            "user_query": user_query,
            "conversation_history": conversation_history or [],
            "attachments": attachments or [],
            "stateful_anchors": stateful_anchors,
        }
    )
    return parser_result_to_payload(parsed)


def invoke_parser_service(
    *,
    user_query: str,
    conversation_history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    stateful_anchors: StatefulAnchors | None = None,
) -> dict[str, Any]:
    return invoke_parser_pipeline(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
        stateful_anchors=stateful_anchors,
    )


def invoke_parser(
    *,
    user_query: str,
    conversation_history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    stateful_anchors: StatefulAnchors | None = None,
) -> dict[str, Any]:
    return invoke_parser_pipeline(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
        stateful_anchors=stateful_anchors,
    )


def _coerce_parser_entity_output(value: Any) -> ParserEntityOutputSpan | None:
    if isinstance(value, ParserEntityOutputSpan):
        return value
    if isinstance(value, Mapping):
        try:
            return ParserEntityOutputSpan.model_validate(value)
        except Exception:
            text = str(value.get("text") or value.get("value") or value.get("raw") or "").strip()
            if not text:
                return None
            raw = str(value.get("raw") or text).strip() or text
            start = value.get("start", -1)
            end = value.get("end", -1)
            try:
                start = int(start)
            except (TypeError, ValueError):
                start = -1
            try:
                end = int(end)
            except (TypeError, ValueError):
                end = -1
            return ParserEntityOutputSpan(text=text, raw=raw, start=start, end=end)
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return ParserEntityOutputSpan(text=cleaned, raw=cleaned)


def _locate_span(query: str, candidate: str, used_ranges: list[tuple[int, int]]) -> tuple[int, int]:
    normalized_query = str(query or "")
    normalized_candidate = str(candidate or "")
    if not normalized_query or not normalized_candidate:
        return -1, -1

    query_lower = normalized_query.lower()
    candidate_lower = normalized_candidate.lower()
    start_index = 0
    while True:
        start = query_lower.find(candidate_lower, start_index)
        if start == -1:
            return -1, -1
        end = start + len(normalized_candidate)
        if all(end <= existing_start or start >= existing_end for existing_start, existing_end in used_ranges):
            used_ranges.append((start, end))
            return start, end
        start_index = start + 1


def _offsets_match(query: str, raw: str, start: int, end: int) -> bool:
    normalized_query = str(query or "")
    normalized_raw = str(raw or "")
    if not normalized_query or not normalized_raw:
        return False
    if start < 0 or end < 0 or end < start or end > len(normalized_query):
        return False
    return normalized_query[start:end].lower() == normalized_raw.lower()


def _resolve_offsets(
    *,
    source_query: str,
    raw: str,
    text: str,
    start: int,
    end: int,
    used_ranges: list[tuple[int, int]],
) -> tuple[int, int]:
    if _offsets_match(source_query, raw, start, end):
        used_ranges.append((start, end))
        return start, end

    for candidate in (raw, text):
        resolved_start, resolved_end = _locate_span(source_query, candidate, used_ranges)
        if resolved_start >= 0:
            return resolved_start, resolved_end

    return -1, -1


def _to_entity_spans(values: list[Any] | None, *, source_query: str = "") -> list[EntitySpan]:
    spans: list[EntitySpan] = []
    used_ranges: list[tuple[int, int]] = []

    for value in values or []:
        parsed_value = _coerce_parser_entity_output(value)
        if parsed_value is None:
            continue
        text = str(parsed_value.text or "").strip()
        raw = str(parsed_value.raw or text).strip() or text
        if not text and not raw:
            continue
        start = parsed_value.start
        end = parsed_value.end
        if source_query:
            start, end = _resolve_offsets(
                source_query=source_query,
                raw=raw,
                text=text,
                start=start,
                end=end,
                used_ranges=used_ranges,
            )

        spans.append(
            EntitySpan(
                text=text or raw,
                raw=raw,
                normalized_value=None,
                start=start,
                end=end,
                attribution=SourceAttribution(
                    source_type="parser",
                    recency="CURRENT_TURN",
                    source_label="parser",
                ),
            )
        )
    return spans


def parser_result_to_payload(parsed: Any) -> dict[str, Any]:
    if hasattr(parsed, "model_dump"):
        return dict(parsed.model_dump())
    if isinstance(parsed, Mapping):
        return dict(parsed)
    raise TypeError("Parser adapter expected a model_dump-capable result or mapping payload")


def _map_parser_context(payload: Mapping[str, Any]) -> ParserContext:
    context = payload.get("context", {}) or {}
    return ParserContext(
        language=str(context.get("language", "other") or "other"),
        channel=str(context.get("channel", "internal_qa") or "internal_qa"),
        semantic_intent=str(context.get("semantic_intent", "unknown") or "unknown"),
        intent_confidence=float(context.get("intent_confidence", 0.0) or 0.0),
        query_type=str(context.get("query_type", "question") or "question"),
        urgency=str(context.get("urgency", "low") or "low"),
        risk_level=str(context.get("risk_level", "low") or "low"),
        needs_human_review=bool(context.get("needs_human_review", False)),
        reasoning_note=str(context.get("reasoning_note", "") or ""),
    )


def _map_parser_request_flags(payload: Mapping[str, Any]) -> ParserRequestFlags:
    flags = payload.get("request_flags", {}) or {}
    return ParserRequestFlags(
        needs_price=bool(flags.get("needs_price", False)),
        needs_timeline=bool(flags.get("needs_timeline", False)),
        needs_protocol=bool(flags.get("needs_protocol", False)),
        needs_customization=bool(flags.get("needs_customization", False)),
        needs_order_status=bool(flags.get("needs_order_status", False)),
        needs_shipping_info=bool(flags.get("needs_shipping_info", False)),
        needs_documentation=bool(flags.get("needs_documentation", False)),
        needs_troubleshooting=bool(flags.get("needs_troubleshooting", False)),
        needs_quote=bool(flags.get("needs_quote", False)),
        needs_availability=bool(flags.get("needs_availability", False)),
        needs_recommendation=bool(flags.get("needs_recommendation", False)),
        needs_comparison=bool(flags.get("needs_comparison", False)),
        needs_invoice=bool(flags.get("needs_invoice", False)),
        needs_refund_or_cancellation=bool(flags.get("needs_refund_or_cancellation", False)),
        needs_sample=bool(flags.get("needs_sample", False)),
        needs_regulatory_info=bool(flags.get("needs_regulatory_info", False)),
    )


def _map_parser_constraints(payload: Mapping[str, Any]) -> ParserConstraints:
    constraints = payload.get("constraints", {}) or {}
    return ParserConstraints(
        budget=constraints.get("budget"),
        timeline_requirement=constraints.get("timeline_requirement"),
        destination=constraints.get("destination"),
        quantity=constraints.get("quantity"),
        grade_or_quality=constraints.get("grade_or_quality"),
        usage_context=constraints.get("usage_context"),
        format_or_size=constraints.get("format_or_size"),
        comparison_target=constraints.get("comparison_target"),
        preferred_supplier_or_brand=constraints.get("preferred_supplier_or_brand"),
    )


def _map_parser_open_slots(payload: Mapping[str, Any]) -> ParserOpenSlots:
    open_slots = payload.get("open_slots", {}) or {}
    return ParserOpenSlots(
        customer_goal=open_slots.get("customer_goal"),
        experiment_type=open_slots.get("experiment_type"),
        pain_point=open_slots.get("pain_point"),
        requested_action=open_slots.get("requested_action"),
        referenced_prior_context=open_slots.get("referenced_prior_context"),
        delivery_or_logistics_note=open_slots.get("delivery_or_logistics_note"),
        regulatory_or_compliance_note=open_slots.get("regulatory_or_compliance_note"),
        other_notes=list(open_slots.get("other_notes", []) or []),
    )


def _map_parser_retrieval_hints(payload: Mapping[str, Any]) -> ParserRetrievalHints:
    hints = payload.get("retrieval_hints", {}) or {}
    return ParserRetrievalHints(
        keywords=list(hints.get("keywords", []) or []),
        expanded_queries=list(hints.get("expanded_queries", []) or []),
        filters=list(hints.get("filters", []) or []),
    )


def _map_selection_resolution(payload: Mapping[str, Any]) -> SelectionResolution | None:
    raw = payload.get("selection_resolution")
    if raw is None:
        return None
    if isinstance(raw, SelectionResolution):
        return raw
    if isinstance(raw, Mapping):
        selected_value = str(raw.get("selected_value", "") or "").strip()
        selected_index = raw.get("selected_index")
        confidence = float(raw.get("selection_confidence", 0.0) or 0.0)
        if not selected_value and selected_index is None:
            return None
        if confidence < 0.1:
            return None
        return SelectionResolution(
            selected_index=selected_index,
            selected_value=selected_value,
            selection_confidence=confidence,
            carries_new_intent=bool(raw.get("carries_new_intent", False)),
            reason=str(raw.get("reason", "") or ""),
        )
    return None


def adapt_parsed_result_to_parser_signals(
    payload: Mapping[str, Any],
    *,
    source_query: str = "",
) -> ParserSignals:
    entities = payload.get("entities", {}) or {}
    return ParserSignals(
        context=_map_parser_context(payload),
        entities=ParserEntitySignals(
            product_names=_to_entity_spans(list(entities.get("product_names", []) or []), source_query=source_query),
            catalog_numbers=_to_entity_spans(list(entities.get("catalog_numbers", []) or []), source_query=source_query),
            service_names=_to_entity_spans(list(entities.get("service_names", []) or []), source_query=source_query),
            targets=_to_entity_spans(list(entities.get("targets", []) or []), source_query=source_query),
            species=_to_entity_spans(list(entities.get("species", []) or []), source_query=source_query),
            applications=_to_entity_spans(list(entities.get("applications", []) or []), source_query=source_query),
            order_numbers=_to_entity_spans(list(entities.get("order_numbers", []) or []), source_query=source_query),
            invoice_numbers=_to_entity_spans(list(entities.get("invoice_numbers", []) or []), source_query=source_query),
            document_names=_to_entity_spans(list(entities.get("document_names", []) or []), source_query=source_query),
            company_names=_to_entity_spans(list(entities.get("company_names", []) or []), source_query=source_query),
            customer_names=_to_entity_spans(list(entities.get("customer_names", []) or []), source_query=source_query),
        ),
        request_flags=_map_parser_request_flags(payload),
        constraints=_map_parser_constraints(payload),
        open_slots=_map_parser_open_slots(payload),
        retrieval_hints=_map_parser_retrieval_hints(payload),
        missing_information=list(payload.get("missing_information", []) or []),
        extra_instructions=payload.get("extra_instructions"),
        selection_resolution=_map_selection_resolution(payload),
    )


def build_parser_signals(
    *,
    user_query: str,
    conversation_history: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    stateful_anchors: StatefulAnchors | None = None,
) -> tuple[ParserSignals, str]:
    """Return (parser_signals, llm_normalized_query).

    The LLM produces a semantically cleaned normalized_query that is
    richer than simple whitespace normalization.  The caller should use
    it to upgrade TurnCore.normalized_query.

    When *stateful_anchors* carries pending clarification options, the
    parser is given those options as context so it can resolve the
    user's selection via selection_resolution.
    """
    parser_payload = invoke_parser(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
        stateful_anchors=stateful_anchors,
    )
    signals = adapt_parsed_result_to_parser_signals(parser_payload, source_query=user_query)
    llm_normalized = str(parser_payload.get("normalized_query", "") or "").strip()
    return signals, llm_normalized
