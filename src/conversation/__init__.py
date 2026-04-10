from __future__ import annotations

from typing import Any


__all__ = ["resolve_reference", "build_routing_memory", "resolve_turn"]


def __getattr__(name: str) -> Any:
    if name == "resolve_reference":
        from .reference_resolution_service import resolve_reference

        return resolve_reference
    if name == "build_routing_memory":
        from .routing_state_service import build_routing_memory

        return build_routing_memory
    if name == "resolve_turn":
        from .turn_resolution_service import resolve_turn

        return resolve_turn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
