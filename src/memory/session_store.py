from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from src.config import get_memory_settings


class SessionStore:
    def __init__(self) -> None:
        self.settings = get_memory_settings()
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.settings.get("is_configured")) and redis is not None

    def _get_client(self):
        if self._client is None and self.is_configured():
            self._client = redis.Redis.from_url(
                self.settings["redis_url"],
                decode_responses=True,
            )
        return self._client

    def _session_key(self, thread_id: str) -> str:
        return f"{self.settings['key_prefix']}:{thread_id}"

    def load_session(self, thread_id: str | None) -> Dict[str, Any]:
        if not thread_id or not self.is_configured():
            return self._empty_session(thread_id)

        client = self._get_client()
        if client is None:
            return self._empty_session(thread_id)

        payload = client.get(self._session_key(thread_id))
        if not payload:
            return self._empty_session(thread_id)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return self._empty_session(thread_id)
        if not isinstance(data, dict):
            return self._empty_session(thread_id)

        return {
            "thread_id": thread_id,
            "recent_turns": data.get("recent_turns", []),
            "route_state": data.get("route_state", {}),
            "updated_at": data.get("updated_at", ""),
        }

    def get_recent_turns(self, thread_id: str | None) -> List[Dict[str, Any]]:
        session = self.load_session(thread_id)
        return session.get("recent_turns", [])

    def append_turns(self, thread_id: str | None, turns: List[Dict[str, Any]]) -> None:
        if not thread_id or not turns or not self.is_configured():
            return

        client = self._get_client()
        if client is None:
            return

        session = self.load_session(thread_id)
        existing_turns = session.get("recent_turns", [])
        merged_turns = self._dedupe_turns(existing_turns + turns)
        max_messages = max(int(self.settings.get("max_turns", 10)) * 2, 2)
        persisted_turns = merged_turns[-max_messages:]
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(
            {
                "thread_id": thread_id,
                "recent_turns": persisted_turns,
                "route_state": session.get("route_state", {}),
                "updated_at": updated_at,
            },
            ensure_ascii=False,
        )
        client.set(self._session_key(thread_id), payload, ex=int(self.settings.get("ttl_seconds", 7200)))

    def update_route_state(self, thread_id: str | None, route_state: Dict[str, Any]) -> None:
        if not thread_id or not self.is_configured():
            return

        client = self._get_client()
        if client is None:
            return

        session = self.load_session(thread_id)
        payload = json.dumps(
            {
                "thread_id": thread_id,
                "recent_turns": session.get("recent_turns", []),
                "route_state": route_state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        client.set(self._session_key(thread_id), payload, ex=int(self.settings.get("ttl_seconds", 7200)))

    def _empty_session(self, thread_id: str | None) -> Dict[str, Any]:
        return {
            "thread_id": thread_id,
            "recent_turns": [],
            "route_state": {},
            "updated_at": "",
        }

    def _dedupe_turns(self, turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for turn in turns:
            signature = json.dumps(
                {
                    "role": turn.get("role", "user"),
                    "content": turn.get("content", ""),
                    "metadata": turn.get("metadata", {}) or {},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(turn)

        return deduped
