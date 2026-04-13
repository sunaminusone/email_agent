from __future__ import annotations

import json
from typing import Any, Dict, List

from src.config import get_memory_settings
from src.memory.adapters.redis_store import RedisSessionAdapter
from src.memory.models import MemorySnapshot
from src.memory.store import load_memory_snapshot, serialize_memory_snapshot, snapshot_to_route_state


class SessionStore:
    def __init__(self) -> None:
        self.settings = get_memory_settings()
        self.adapter = RedisSessionAdapter(self.settings)

    def is_configured(self) -> bool:
        return self.adapter.is_configured()

    def _get_client(self):
        return self.adapter.get_client()

    def _session_key(self, thread_id: str) -> str:
        return self.adapter.session_key(thread_id)

    def load_session(self, thread_id: str | None) -> Dict[str, Any]:
        data = self.adapter.load(thread_id)
        if data is None:
            return self._empty_session(thread_id)

        return {
            "thread_id": thread_id,
            "recent_turns": data.get("recent_turns", []),
            "memory_snapshot": data.get("memory_snapshot", {}),
            "route_state": data.get("route_state", {}),
            "updated_at": data.get("updated_at", ""),
        }

    def get_recent_turns(self, thread_id: str | None) -> List[Dict[str, Any]]:
        session = self.load_session(thread_id)
        return session.get("recent_turns", [])

    def load_memory_snapshot(self, thread_id: str | None) -> MemorySnapshot:
        session = self.load_session(thread_id)
        snapshot_source = session.get("memory_snapshot") or session.get("route_state")
        return load_memory_snapshot(snapshot_source, thread_id=thread_id)

    def append_turns(self, thread_id: str | None, turns: List[Dict[str, Any]]) -> None:
        if not thread_id or not turns or not self.is_configured():
            return

        session = self.load_session(thread_id)
        existing_turns = session.get("recent_turns", [])
        merged_turns = self._dedupe_turns(existing_turns + turns)
        max_messages = max(int(self.settings.get("max_turns", 10)) * 2, 2)
        persisted_turns = merged_turns[-max_messages:]
        self.adapter.save(
            thread_id,
            {
                "recent_turns": persisted_turns,
                "memory_snapshot": session.get("memory_snapshot", {}),
                "route_state": session.get("route_state", {}),
            },
        )

    def update_route_state(self, thread_id: str | None, route_state: Dict[str, Any]) -> None:
        if not thread_id or not self.is_configured():
            return

        session = self.load_session(thread_id)
        self.adapter.save(
            thread_id,
            {
                "recent_turns": session.get("recent_turns", []),
                "memory_snapshot": session.get("memory_snapshot", {}),
                "route_state": route_state,
            },
        )

    def update_memory_snapshot(self, thread_id: str | None, snapshot: MemorySnapshot) -> None:
        if not thread_id or not self.is_configured():
            return

        session = self.load_session(thread_id)
        self.adapter.save(
            thread_id,
            {
                "recent_turns": session.get("recent_turns", []),
                "memory_snapshot": serialize_memory_snapshot(snapshot),
                "route_state": session.get("route_state", {}),
            },
        )

    def persist_memory_snapshot(
        self,
        thread_id: str | None,
        snapshot: MemorySnapshot,
        *,
        route_phase: str = "active",
        last_assistant_prompt_type: str = "",
        session_payload: Dict[str, Any] | None = None,
        extra_updates: Dict[str, Any] | None = None,
    ) -> None:
        route_state = snapshot_to_route_state(
            snapshot,
            route_phase=route_phase,
            last_assistant_prompt_type=last_assistant_prompt_type,
            session_payload=session_payload,
            extra_updates=extra_updates,
        )
        if not thread_id or not self.is_configured():
            return

        session = self.load_session(thread_id)
        self.adapter.save(
            thread_id,
            {
                "recent_turns": session.get("recent_turns", []),
                "memory_snapshot": serialize_memory_snapshot(snapshot),
                "route_state": route_state,
            },
        )

    def _empty_session(self, thread_id: str | None) -> Dict[str, Any]:
        return {
            "thread_id": thread_id,
            "recent_turns": [],
            "memory_snapshot": {},
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
