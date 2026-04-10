from __future__ import annotations

from typing import Any

from src.execution.models import PlannedToolCall
from src.objects.models import ObjectCandidate
from src.tools.models import ToolRequest


def build_tool_request(intent, tool_name: str) -> ToolRequest:
    request = ToolRequest(
        tool_name=tool_name,
        query=_tool_query(intent, tool_name),
        primary_object=_to_tool_object(intent.primary_object),
        secondary_objects=[_to_tool_object(item) for item in intent.secondary_objects],
        dialogue_act=intent.dialogue_act,
        modality_decision=intent.modality_decision,
        constraints=_base_constraints(intent),
    )
    return _enrich_tool_request(request, intent, tool_name)


def attach_requests(intent, planned_calls: list[dict]) -> list[PlannedToolCall]:
    hydrated_calls: list[PlannedToolCall] = []
    for call in planned_calls:
        hydrated_calls.append(
            PlannedToolCall(
                call_id=call["call_id"],
                tool_name=call["tool_name"],
                request=build_tool_request(intent, call["tool_name"]),
                role=call["role"],
                priority=call["priority"],
                can_run_in_parallel=call["can_run_in_parallel"],
                depends_on=call["depends_on"],
            )
        )
    return hydrated_calls


def _to_tool_object(object_ref):
    if object_ref is None:
        return None
    return ObjectCandidate(
        object_type=object_ref.object_type,
        canonical_value=object_ref.canonical_value,
        display_name=object_ref.display_name,
        identifier=object_ref.identifier,
        identifier_type=object_ref.identifier_type,
        business_line=object_ref.business_line,
    )


def _tool_query(intent, tool_name: str) -> str:
    query = str(getattr(intent, "query", "") or "").strip()
    if not query:
        return ""
    if tool_name == "technical_rag_tool":
        return query
    if tool_name == "document_lookup_tool":
        return query
    if tool_name in {"catalog_lookup_tool", "pricing_lookup_tool"}:
        return query
    return query


def _base_constraints(intent) -> dict[str, Any]:
    primary_object = _to_tool_object(intent.primary_object)
    secondary_objects = [_to_tool_object(item) for item in intent.secondary_objects]
    common_constraints = {
        "resolved_object_constraints": dict(intent.resolved_object_constraints),
        "ambiguity_count": len(intent.ambiguous_objects),
        "ambiguous_objects": [_serialize_ambiguity(item) for item in intent.ambiguous_objects],
    }
    scope_context = _build_scope_context(
        query=getattr(intent, "query", ""),
        primary_object=primary_object,
        secondary_objects=secondary_objects,
        intent=intent,
    )
    retrieval_hints = _build_retrieval_hints(intent)
    debug_context = {
        "selected_tools": list(intent.selected_tools),
        "intent_reason": intent.reason,
    }

    return {
        "common": common_constraints,
        "scope": scope_context,
        "retrieval": {
            "hints": retrieval_hints,
            "preferred_modalities": list(retrieval_hints.get("preferred_modalities", [])),
            "dialogue_act": retrieval_hints.get("dialogue_act", ""),
            "business_line": retrieval_hints.get("business_line", ""),
        },
        "tool": {},
        "debug": debug_context,
    }


def _enrich_tool_request(request: ToolRequest, intent, tool_name: str) -> ToolRequest:
    constraints = request.constraints.to_dict()
    tool_bucket = dict(constraints.get("tool", {}))

    if tool_name in {"catalog_lookup_tool", "pricing_lookup_tool"}:
        tool_bucket["catalog"] = _catalog_constraints(intent)
    elif tool_name == "document_lookup_tool":
        tool_bucket["documents"] = _document_constraints(intent)
    elif tool_name == "technical_rag_tool":
        tool_bucket["rag"] = _rag_constraints(intent)
    elif tool_name in {
        "customer_lookup_tool",
        "invoice_lookup_tool",
        "order_lookup_tool",
        "shipping_lookup_tool",
    }:
        tool_bucket["quickbooks"] = _quickbooks_constraints(intent, tool_name)

    constraints["tool"] = tool_bucket
    request.constraints = constraints
    return request


def _catalog_constraints(intent) -> dict[str, str]:
    resolved = dict(intent.resolved_object_constraints)
    return {
        "catalog_number": _first_non_empty(
            resolved.get("catalog_number"),
            resolved.get("catalog_no"),
            resolved.get("identifier"),
        ),
        "product_name": _first_non_empty(
            resolved.get("product_name"),
            resolved.get("canonical_value"),
            resolved.get("display_name"),
        ),
        "service_name": resolved.get("service_name", ""),
        "target": resolved.get("target", ""),
        "application": resolved.get("application", ""),
        "species": resolved.get("species", ""),
        "business_line": resolved.get("business_line", ""),
    }


def _document_constraints(intent) -> dict[str, str]:
    resolved = dict(intent.resolved_object_constraints)
    return {
        "document_name": _first_non_empty(
            resolved.get("document_name"),
            resolved.get("document_title"),
            resolved.get("display_name") if resolved.get("object_type") == "document" else "",
        ),
        "catalog_number": _first_non_empty(
            resolved.get("catalog_number"),
            resolved.get("catalog_no"),
            resolved.get("identifier"),
        ),
        "product_name": _first_non_empty(
            resolved.get("product_name"),
            resolved.get("canonical_value"),
        ),
        "business_line": resolved.get("business_line", ""),
    }


def _rag_constraints(intent) -> dict[str, Any]:
    resolved = dict(intent.resolved_object_constraints)
    primary_object = _to_tool_object(intent.primary_object)
    return {
        "business_line": resolved.get("business_line", ""),
        "active_object_type": primary_object.object_type if primary_object is not None else "",
        "active_object_name": (
            primary_object.canonical_value or primary_object.display_name
            if primary_object is not None
            else ""
        ),
        "target": resolved.get("target", ""),
        "retrieval_hints": _build_retrieval_hints(intent),
    }


def _quickbooks_constraints(intent, tool_name: str) -> dict[str, str]:
    resolved = dict(intent.resolved_object_constraints)
    primary_object = _to_tool_object(intent.primary_object)
    primary_label = ""
    primary_identifier = ""
    if primary_object is not None:
        primary_label = primary_object.canonical_value or primary_object.display_name
        primary_identifier = primary_object.identifier

    destination = _first_non_empty(
        resolved.get("destination"),
        resolved.get("ship_to"),
    )
    customer_name = _first_non_empty(
        resolved.get("customer_name"),
        resolved.get("company_name"),
        primary_label if primary_object is not None and primary_object.object_type == "customer" else "",
    )
    order_number = _first_non_empty(
        resolved.get("order_number"),
        resolved.get("doc_number"),
        resolved.get("invoice_number"),
        primary_identifier if primary_object is not None and primary_object.object_type in {"order", "invoice", "shipment"} else "",
    )

    return {
        "customer_name": customer_name,
        "order_number": order_number,
        "destination": destination,
        "tool_name": tool_name,
    }


def _build_scope_context(*, query: str, primary_object, secondary_objects, intent) -> dict[str, Any]:
    primary_label = ""
    if primary_object is not None:
        primary_label = primary_object.canonical_value or primary_object.display_name or primary_object.identifier

    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "primary_intent": _dialogue_act_label(intent),
        },
        "primary_object": _serialize_object(primary_object),
        "secondary_objects": [_serialize_object(item) for item in secondary_objects],
        "entities": _scope_entities(primary_object, secondary_objects),
        "active_service_name": primary_label if primary_object is not None and primary_object.object_type == "service" else "",
        "active_product_name": primary_label if primary_object is not None and primary_object.object_type == "product" else "",
        "active_target": primary_label if primary_object is not None and primary_object.object_type == "scientific_target" else "",
        "turn_resolution": {
            "turn_type": "follow_up" if primary_object is not None else "",
        },
        "routing_memory": {
            "should_stick_to_active_route": bool(primary_object),
        },
    }


def _build_retrieval_hints(intent) -> dict[str, Any]:
    primary_object = _to_tool_object(intent.primary_object)
    hints: dict[str, Any] = {
        "preferred_modalities": [intent.modality_decision.primary_modality, *intent.modality_decision.supporting_modalities],
        "dialogue_act": intent.dialogue_act.act,
    }
    if primary_object is not None:
        label = primary_object.canonical_value or primary_object.display_name
        if label:
            hints["primary_object_name"] = label
        if primary_object.business_line:
            hints["business_line"] = primary_object.business_line
    return hints


def _serialize_ambiguity(item) -> dict[str, Any]:
    return {
        "object_type": item.object_type,
        "query_value": item.query_value,
        "ambiguity_kind": item.ambiguity_kind,
        "clarification_focus": item.clarification_focus,
        "suggested_disambiguation_fields": list(item.suggested_disambiguation_fields),
        "reason": item.reason,
        "candidate_refs": [_serialize_execution_object(ref) for ref in item.candidate_refs],
    }


def _serialize_execution_object(object_ref) -> dict[str, str]:
    return {
        "object_type": object_ref.object_type,
        "canonical_value": object_ref.canonical_value,
        "display_name": object_ref.display_name,
        "identifier": object_ref.identifier,
        "identifier_type": object_ref.identifier_type,
        "business_line": object_ref.business_line,
    }


def _serialize_object(object_ref: ObjectCandidate | None) -> dict[str, str]:
    if object_ref is None:
        return {}
    return {
        "object_type": object_ref.object_type,
        "canonical_value": object_ref.canonical_value,
        "display_name": object_ref.display_name,
        "identifier": object_ref.identifier,
        "identifier_type": object_ref.identifier_type,
        "business_line": object_ref.business_line,
    }


def _scope_entities(primary_object: ObjectCandidate | None, secondary_objects: list[ObjectCandidate]) -> dict[str, list[str]]:
    objects = [item for item in [primary_object, *secondary_objects] if item is not None]
    entities = {
        "service_names": [],
        "product_names": [],
        "catalog_numbers": [],
        "targets": [],
        "company_names": [],
        "order_numbers": [],
        "document_names": [],
    }
    for item in objects:
        label = item.canonical_value or item.display_name
        if item.object_type == "service" and label:
            entities["service_names"].append(label)
        elif item.object_type == "product":
            if label:
                entities["product_names"].append(label)
            if item.identifier:
                entities["catalog_numbers"].append(item.identifier)
        elif item.object_type == "scientific_target" and label:
            entities["targets"].append(label)
        elif item.object_type == "customer" and label:
            entities["company_names"].append(label)
        elif item.object_type in {"order", "invoice", "shipment"} and item.identifier:
            entities["order_numbers"].append(item.identifier)
        elif item.object_type == "document" and label:
            entities["document_names"].append(label)

    return {key: _dedupe_list(values) for key, values in entities.items()}


def _dialogue_act_label(intent) -> str:
    mapping = {
        "INQUIRY": "technical_question",
        "ELABORATE": "technical_question",
        "SELECTION": "selection",
        "ACKNOWLEDGE": "acknowledge",
        "TERMINATE": "terminate",
    }
    return mapping.get(intent.dialogue_act.act, "unknown")


def _dedupe_list(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _first_non_empty(*values: Any) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""
