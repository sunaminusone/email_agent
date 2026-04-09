from typing import Any, Dict

from src.schemas import ExecutedAction
from src.documents.service import lookup_documents
from src.rag.service import retrieve_technical_knowledge


def execute_documentation_lookup(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    entities = agent_input.get("entities", {})
    routing_debug = agent_input.get("routing_debug", {})
    output = lookup_documents(
        query=agent_input.get("retrieval_query") or agent_input.get("effective_query") or agent_input.get("query", ""),
        catalog_numbers=entities.get("catalog_numbers", []),
        product_names=entities.get("product_names", []),
        document_names=entities.get("document_names", []),
        business_line_hint=routing_debug.get("business_line", ""),
    )
    documents_found = output.get("documents_found", 0)
    status = "completed" if documents_found else "not_found"
    summary = (
        f"Found {documents_found} matching document(s)."
        if documents_found
        else "No matching documents were found."
    )
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status=status,
        summary=summary,
        output=output,
    )


def execute_technical_lookup(action, agent_input: Dict[str, Any]) -> ExecutedAction:
    retrieval_hints = agent_input.get("retrieval_hints", {})
    entities = agent_input.get("entities", {})
    routing_debug = agent_input.get("routing_debug", {})
    output = retrieve_technical_knowledge(
        query=agent_input.get("retrieval_query") or agent_input.get("effective_query") or agent_input.get("query", ""),
        business_line_hint=agent_input.get("active_business_line", "") or routing_debug.get("business_line", ""),
        retrieval_hints=retrieval_hints,
        active_service_name=agent_input.get("active_service_name", ""),
        active_product_name=agent_input.get("active_product_name", ""),
        active_target=agent_input.get("active_target", ""),
        product_names=entities.get("product_names", []),
        service_names=entities.get("service_names", []),
        targets=entities.get("targets", []),
        scope_context=agent_input,
    )
    documents_found = output.get("documents_found", 0)
    status = "completed" if documents_found else "not_found"
    summary = (
        f"Retrieved {documents_found} technical evidence chunk(s)."
        if documents_found
        else "No technical evidence chunks were retrieved."
    )
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status=status,
        summary=summary,
        output=output,
    )
