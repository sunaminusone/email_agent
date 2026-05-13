from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None


class RedisSessionAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.settings.get("is_configured")) and redis is not None

    def get_client(self):
        if self._client is None and self.is_configured():
            self._client = redis.Redis.from_url(
                self.settings["redis_url"],
                decode_responses=True,
            )
        return self._client

    def session_key(self, thread_id: str) -> str:
        return f"{self.settings['key_prefix']}:{thread_id}"

    def load(self, thread_id: str | None) -> dict[str, Any] | None:
        if not thread_id or not self.is_configured():
            return None

        client = self.get_client()
        if client is None:
            return None

        payload = client.get(self.session_key(thread_id))
        if not payload:
            return None

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def save(self, thread_id: str | None, payload: dict[str, Any]) -> None:
        if not thread_id or not self.is_configured():
            return

        client = self.get_client()
        if client is None:
            return

        serialized = json.dumps(
            {
                **payload,
                "thread_id": thread_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        client.set(
            self.session_key(thread_id),
            serialized,
            ex=int(self.settings.get("ttl_seconds", 7200)),
        )

    def delete(self, thread_id: str | None) -> None:
        if not thread_id or not self.is_configured():
            return

        client = self.get_client()
        if client is None:
            return

        client.delete(self.session_key(thread_id))
