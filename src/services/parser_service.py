import json
from typing import Optional, List, Dict, Any

from src.chains import build_parser_chain
from src.schemas import ParsedResult


def parse_user_input(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> ParsedResult:
    conversation_history = conversation_history or []
    attachments = attachments or []

    parser_chain = build_parser_chain()

    parsed = parser_chain.invoke(
        {
            "user_query": user_query,
            "conversation_history": json.dumps(
                conversation_history,
                ensure_ascii=False,
                indent=2,
            ),
            "attachments": json.dumps(
                attachments,
                ensure_ascii=False,
                indent=2,
            ),
        }
    )

    return parsed