from typing import Any, Dict, List, Optional

from src.parser.chain import build_parser_pipeline
from src.schemas import ParsedResult


def parse_user_input(
    user_query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> ParsedResult:
    parser_pipeline = build_parser_pipeline()
    return parser_pipeline.invoke(
        {
            "user_query": user_query,
            "conversation_history": conversation_history or [],
            "attachments": attachments or [],
        }
    )
