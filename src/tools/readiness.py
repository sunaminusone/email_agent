"""Readiness evaluation: tool self-assesses feasibility against current context.

Three-layer model: check full_identifiers → degraded_identifiers → insufficient.
Pure function — no external state, no LLM calls.
"""
from __future__ import annotations

from src.tools.models import ToolCapability, ToolReadiness


def check_readiness(
    capability: ToolCapability,
    available_params: dict[str, str],
) -> ToolReadiness:
    """Evaluate whether *capability* can execute given *available_params*.

    Returns :class:`ToolReadiness` with quality = full / degraded / insufficient.

    Logic:
    - No identifiers declared → always full (RAG, catalog).
    - Any full_identifier present → full (exact match, unique result).
    - Any degraded_identifier present → degraded (fuzzy, may return multiple).
    - Otherwise → insufficient.
    """
    if not capability.full_identifiers and not capability.degraded_identifiers:
        return ToolReadiness(
            tool_name=capability.tool_name,
            can_execute=True,
            quality="full",
            reason="No identifiers required; tool can run freely.",
        )

    for p in capability.full_identifiers:
        if _has_param(p, available_params):
            return ToolReadiness(
                tool_name=capability.tool_name,
                can_execute=True,
                quality="full",
                matched_identifier=p,
                reason=f"Full identifier '{p}' available.",
            )

    for p in capability.degraded_identifiers:
        if _has_param(p, available_params):
            return ToolReadiness(
                tool_name=capability.tool_name,
                can_execute=True,
                quality="degraded",
                matched_identifier=p,
                reason=f"Degraded identifier '{p}' available; results may not be unique.",
            )

    all_ids = capability.full_identifiers + capability.degraded_identifiers
    return ToolReadiness(
        tool_name=capability.tool_name,
        can_execute=False,
        quality="insufficient",
        missing_identifiers=all_ids,
        reason=f"Missing all identifiers: {all_ids}",
    )


def _has_param(param_name: str, available: dict[str, str]) -> bool:
    """Check whether a parameter is present and non-empty."""
    value = available.get(param_name, "")
    return bool(value and value.strip())
