from typing import Optional, List, Dict, Any

from src.schemas import ParsedResult
from src.services.parser_service import parse_user_input


def build_agent_input(
    original_query: str,
    parsed: ParsedResult,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    conversation_history = conversation_history or []
    attachments = attachments or []

    return {
        "query": parsed.normalized_query or original_query.strip(),
        "context": parsed.context.model_dump(),
        "entities": parsed.entities.model_dump(),
        "request_flags": parsed.request_flags.model_dump(),
        "constraints": parsed.constraints.model_dump(),
        "open_slots": parsed.open_slots.model_dump(),
        "retrieval_hints": parsed.retrieval_hints.model_dump(),
        "tool_hints": parsed.tool_hints.model_dump(),
        "missing_information": parsed.missing_information,
        "conversation_history": conversation_history,
        "attachments": attachments,
        "extra_instructions": parsed.extra_instructions,
    }


def make_agent_input(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    parsed = parse_user_input(
        user_query=user_query,
        conversation_history=conversation_history,
        attachments=attachments,
    )

    return build_agent_input(
        original_query=user_query,
        parsed=parsed,
        conversation_history=conversation_history,
        attachments=attachments,
    )
