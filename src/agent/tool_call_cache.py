"""Cross-group tool call cache.

Shared across intent groups within a single turn to:
1. **Deduplicate**: if group A already called catalog_lookup_tool for the same
   object, group B reuses the result instead of calling again.
2. **Observe**: group B can see what group A discovered (e.g., a product name
   from catalog) and use it to enrich its own tool requests (e.g., RAG scope).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.common.execution_models import ExecutedToolCall


class CacheKey(BaseModel):
    """Identifies a unique tool call by tool name + object identity."""
    model_config = ConfigDict(frozen=True)

    tool_name: str
    object_type: str = ""
    object_identifier: str = ""

    def __hash__(self) -> int:
        return hash((self.tool_name, self.object_type, self.object_identifier))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CacheKey):
            return NotImplemented
        return (
            self.tool_name == other.tool_name
            and self.object_type == other.object_type
            and self.object_identifier == other.object_identifier
        )


class ToolCallCache(BaseModel):
    """Shared cache across intent groups within a single agent turn."""
    model_config = ConfigDict(extra="forbid")

    _cache: dict[CacheKey, ExecutedToolCall] = {}
    _observations: dict[str, Any] = {}

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "_cache", {})
        object.__setattr__(self, "_observations", {})

    # --- Deduplication ---

    def get_cached(self, tool_name: str, object_type: str = "", object_identifier: str = "") -> ExecutedToolCall | None:
        """Return a cached result if the same tool+object was already called."""
        key = CacheKey(tool_name=tool_name, object_type=object_type, object_identifier=object_identifier)
        return self._cache.get(key)

    def store(self, call: ExecutedToolCall, object_type: str = "", object_identifier: str = "") -> None:
        """Store an executed call in the cache and extract observations."""
        key = CacheKey(tool_name=call.tool_name, object_type=object_type, object_identifier=object_identifier)
        self._cache[key] = call
        self._extract_observations(call)

    # --- Cross-group observations ---

    @property
    def observations(self) -> dict[str, Any]:
        """Accumulated observations from all cached calls."""
        return dict(self._observations)

    @property
    def discovered_product_name(self) -> str:
        return str(self._observations.get("product_name", ""))

    @property
    def discovered_service_name(self) -> str:
        return str(self._observations.get("service_name", ""))

    @property
    def discovered_business_line(self) -> str:
        return str(self._observations.get("business_line", ""))

    def _extract_observations(self, call: ExecutedToolCall) -> None:
        """Extract reusable facts from a tool result for downstream groups."""
        result = call.result
        if result is None or call.status != "ok":
            return

        # Extract from primary records
        for record in result.primary_records[:1]:
            for key in ("display_name", "name", "product_name", "service_name"):
                value = str(record.get(key, "")).strip()
                if value and key not in self._observations:
                    normalized_key = "product_name" if key in ("display_name", "name") else key
                    self._observations.setdefault(normalized_key, value)

            bl = str(record.get("business_line", "")).strip()
            if bl:
                self._observations.setdefault("business_line", bl)

        # Extract from structured facts
        facts = result.structured_facts
        for key in ("product_name", "service_name", "business_line"):
            value = str(facts.get(key, "")).strip()
            if value:
                self._observations.setdefault(key, value)
