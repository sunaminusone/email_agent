import json
from typing import Any, Dict, List


def preprocess_parser_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_query = str(payload.get("user_query") or "").strip()
    conversation_history = payload.get("conversation_history") or []
    attachments = payload.get("attachments") or []

    return {
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
        "_meta": {
            "raw_user_query": user_query,
            "conversation_history_raw": conversation_history,
            "attachments_raw": attachments,
        },
    }
