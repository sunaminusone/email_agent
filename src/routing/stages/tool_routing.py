from __future__ import annotations

from src.routing.models import DialogueActResult, ModalityDecision, RoutedObjectState
from src.routing.utils import normalize_routing_text
from src.routing.vocabulary import ToolName


def select_tools(
    query: str,
    object_routing: RoutedObjectState,
    dialogue_act: DialogueActResult,
    modality_decision: ModalityDecision,
) -> tuple[list[ToolName], str]:
    if object_routing.should_block_execution and object_routing.ambiguous_objects:
        return [], "Tool execution is deferred because object ambiguity still requires clarification."

    if dialogue_act.act in {"ACKNOWLEDGE", "TERMINATE", "UNKNOWN"}:
        return [], "No tools were selected because this dialogue act does not require execution."

    if dialogue_act.act == "SELECTION" and object_routing.primary_object is None:
        return [], "Selection turns should update object state before normal execution continues."

    primary_object = object_routing.primary_object or object_routing.active_object
    if primary_object is None:
        return [], "No tools were selected because no primary object was resolved."

    text = normalize_routing_text(query or "")
    object_type = primary_object.object_type
    modality = modality_decision.primary_modality
    tools: list[ToolName] = []

    if object_type == "product":
        if modality in {"structured_lookup", "hybrid"}:
            tools.append("catalog_lookup_tool")
        if modality in {"unstructured_retrieval", "hybrid"}:
            tools.append("technical_rag_tool")
    elif object_type in {"service", "scientific_target"}:
        if modality == "structured_lookup":
            tools.append("document_lookup_tool")
        else:
            tools.append("technical_rag_tool")
            if modality == "hybrid":
                tools.append("document_lookup_tool")
    elif object_type == "document":
        tools.append("document_lookup_tool")
    elif object_type == "order":
        tools.append("order_lookup_tool")
        if any(term in text for term in {"shipping", "tracking", "delivery"}):
            tools.append("shipping_lookup_tool")
    elif object_type == "shipment":
        tools.append("shipping_lookup_tool")
    elif object_type == "invoice":
        tools.append("invoice_lookup_tool")
    elif object_type == "customer":
        tools.append("customer_lookup_tool")

    deduped = list(dict.fromkeys(tools))
    if not deduped:
        return [], "No tool mapping matched the current object, dialogue act, and modality combination."

    return deduped, "Selected tools from the layered routing stack."
