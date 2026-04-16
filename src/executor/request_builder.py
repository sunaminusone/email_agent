from __future__ import annotations

from typing import Any

from src.common.utils import dedupe_strings
from src.executor.models import ExecutionContext
from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult
from src.tools.models import ToolRequest


def build_tool_request(
    context: ExecutionContext,
    tool_name: str,
    *,
    selected_tools: list[str] | None = None,
) -> ToolRequest:
    """Build a ToolRequest directly from ExecutionContext."""
    return ToolRequest(
        tool_name=tool_name,
        query=context.query,
        primary_object=context.primary_object,
        secondary_objects=list(context.secondary_objects),
        dialogue_act=context.dialogue_act,
        constraints=_base_constraints(context, selected_tools=selected_tools or []),
    )


def _base_constraints(
    context: ExecutionContext,
    *,
    selected_tools: list[str],
) -> dict[str, Any]:
    primary_object = context.primary_object
    secondary_objects = list(context.secondary_objects)
    common_constraints = {
        "resolved_object_constraints": dict(context.resolved_object_constraints),
        "ambiguity_count": 0,
        "ambiguous_objects": [],
    }
    scope_context = _build_scope_context(
        query=context.query,
        primary_object=primary_object,
        secondary_objects=secondary_objects,
        dialogue_act=context.dialogue_act,
    )
    retrieval_hints = _build_retrieval_hints(context)
    debug_context = {
        "selected_tools": list(selected_tools),
        "intent_reason": "",
        "semantic_demand": _build_demand_debug(context),
    }

    return {
        "common": common_constraints,
        "scope": scope_context,
        "retrieval": {
            "hints": retrieval_hints,
            "preferred_modalities": list(retrieval_hints.get("preferred_modalities", [])),
            "dialogue_act": retrieval_hints.get("dialogue_act", ""),
            "business_line": retrieval_hints.get("business_line", ""),
            "demand": _build_retrieval_demand(context),
        },
        "tool": _build_parser_tool_constraints(context),
        "debug": debug_context,
    }



def _build_parser_tool_constraints(context: ExecutionContext) -> dict[str, Any]:
    """Extract non-None parser constraints and open slots into a flat dict.

    Tools consume these via ``request.constraints.tool.get("field_name")``.
    Only non-empty values are included to avoid noise.
    """
    result: dict[str, Any] = {}
    if context.parser_constraints is not None:
        for key, value in context.parser_constraints.model_dump().items():
            if value is not None:
                result[key] = value
    if context.parser_open_slots is not None:
        for key, value in context.parser_open_slots.model_dump().items():
            if value is not None and value != []:
                result[key] = value
    return result


def _build_scope_context(
    *,
    query: str,
    primary_object: ObjectCandidate | None,
    secondary_objects: list[ObjectCandidate],
    dialogue_act: DialogueActResult,
) -> dict[str, Any]:
    primary_label = ""
    if primary_object is not None:
        primary_label = primary_object.canonical_value or primary_object.display_name or primary_object.identifier

    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "primary_intent": _dialogue_act_label(dialogue_act),
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


def _build_retrieval_hints(context: ExecutionContext) -> dict[str, Any]:
    primary = context.primary_object
    hints: dict[str, Any] = {
        "preferred_modalities": [],
        "dialogue_act": context.dialogue_act.act,
    }
    if primary is not None:
        label = primary.canonical_value or primary.display_name
        if label:
            hints["primary_object_name"] = label
        if primary.business_line:
            hints["business_line"] = primary.business_line
    return hints


def _build_retrieval_demand(context: ExecutionContext) -> dict[str, Any]:
    active_demand = context.active_demand
    if active_demand is None:
        return {}
    return {
        "primary_demand": active_demand.primary_demand,
        "secondary_demands": list(active_demand.secondary_demands),
        "request_flags": list(active_demand.request_flags),
    }


def _build_demand_debug(context: ExecutionContext) -> dict[str, Any]:
    profile = context.demand_profile
    active_demand = context.active_demand
    return {
        "profile_primary_demand": profile.primary_demand if profile is not None else "",
        "profile_secondary_demands": list(profile.secondary_demands) if profile is not None else [],
        "active_demand": active_demand.model_dump(mode="json") if active_demand is not None else {},
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

    return {key: dedupe_strings(values) for key, values in entities.items()}


def _dialogue_act_label(dialogue_act: DialogueActResult) -> str:
    mapping = {
        "inquiry": "technical_question",
        "selection": "selection",
        "closing": "acknowledge",
    }
    return mapping.get(dialogue_act.act, "unknown")


