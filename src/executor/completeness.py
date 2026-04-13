"""Evaluate whether execution results are sufficient to answer the customer.

Demand-aware completeness: checks whether the user's information demands
(derived from flags and intent) have been met, not whether retrieval
modalities are covered.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.executor.models import ExecutedToolCall, ExecutionContext
from src.tools.registry import list_registry_entries


Verdict = Literal[
    "sufficient",
    "retry_with_fallback",
    "retry_add_tool",
    "done_partial",
    "done_empty",
    "done_error",
]


class CompletenessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict = "sufficient"
    reason: str = ""
    suggest_tool: str = ""


def evaluate_completeness(
    context: ExecutionContext,
    executed_calls: list[ExecutedToolCall],
    iteration: int,
    max_iterations: int,
) -> CompletenessResult:
    """Evaluate whether the current execution results are sufficient."""
    statuses = [call.status for call in executed_calls]
    called_tools = {call.tool_name for call in executed_calls}
    has_retries = iteration < max_iterations - 1

    # Rule 1: Max iterations reached → done
    if not has_retries:
        if any(s == "ok" for s in statuses):
            return CompletenessResult(verdict="sufficient", reason="Max iterations reached with some results.")
        return CompletenessResult(verdict="done_empty", reason="Max iterations reached.")

    # Rule 2: All tools returned error → done
    if statuses and all(s == "error" for s in statuses):
        return CompletenessResult(verdict="done_error", reason="All tools returned errors.")

    # Rule 3: Primary tool returned ok — check for unsatisfied demands
    for call in executed_calls:
        if call.role == "primary" and call.status == "ok" and _has_meaningful_data(call):
            unsatisfied = _find_unsatisfied_demand(context, called_tools)
            if unsatisfied:
                return CompletenessResult(
                    verdict="retry_add_tool",
                    reason=f"Primary ok but demand unsatisfied: {unsatisfied.reason}",
                    suggest_tool=unsatisfied.suggest_tool,
                )
            return CompletenessResult(verdict="sufficient", reason="Primary tool returned grounded data.")

    # Rule 4: Some ok, some error → done with partial results
    if any(s == "ok" for s in statuses) and any(s == "error" for s in statuses):
        return CompletenessResult(verdict="done_partial", reason="Partial success — some tools errored.")

    # Rule 5: All empty, retries remain → suggest fallback based on demand
    if statuses and all(s == "empty" for s in statuses):
        fallback = _suggest_demand_fallback(context, called_tools)
        if fallback:
            return CompletenessResult(
                verdict="retry_with_fallback",
                reason=f"All tools returned empty. Trying: {fallback}.",
                suggest_tool=fallback,
            )
        return CompletenessResult(verdict="done_empty", reason="All tools returned empty; no fallback available.")

    # Rule 6: Some ok results → sufficient
    if any(s == "ok" for s in statuses):
        return CompletenessResult(verdict="sufficient", reason="At least one tool returned results.")

    return CompletenessResult(verdict="done_empty", reason="No sufficient results and no further actions available.")


# ---------------------------------------------------------------------------
# Demand satisfaction checks
# ---------------------------------------------------------------------------

class _UnsatisfiedDemand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = ""
    suggest_tool: str = ""


def _find_unsatisfied_demand(
    context: ExecutionContext,
    called_tools: set[str],
) -> _UnsatisfiedDemand | None:
    """Check if any active request_flag maps to a tool that hasn't been called.

    Reads flags exclusively from active_demand (GroupDemand) — no
    fallback to raw request_flags.  GroupDemand is the single source
    of truth for demand semantics.
    """
    if context.active_demand is None:
        return None

    active_flags = set(context.active_demand.request_flags)
    if not active_flags:
        return None

    # Build flag → tool mapping from registry capabilities
    flag_to_tools = _build_flag_tool_map()

    for flag in active_flags:
        candidate_tools = flag_to_tools.get(flag, set())
        if candidate_tools and not (candidate_tools & called_tools):
            # This flag's demand hasn't been served by any called tool
            best = _pick_best_uncalled(candidate_tools, called_tools)
            if best:
                return _UnsatisfiedDemand(
                    reason=f"flag={flag} not covered by called tools",
                    suggest_tool=best,
                )

    return None


def _build_flag_tool_map() -> dict[str, set[str]]:
    """Map each request_flag to the set of tools that declare support for it."""
    mapping: dict[str, set[str]] = {}
    for entry in list_registry_entries():
        cap = entry.capability
        if cap is None:
            continue
        for flag in cap.supported_request_flags:
            mapping.setdefault(flag, set()).add(cap.tool_name)
    return mapping


def _pick_best_uncalled(candidate_tools: set[str], called_tools: set[str]) -> str:
    """Pick an uncalled tool from candidates."""
    uncalled = candidate_tools - called_tools
    return next(iter(sorted(uncalled)), "")


def _suggest_demand_fallback(
    context: ExecutionContext,
    called_tools: set[str],
) -> str:
    """When all tools returned empty, suggest a tool based on unsatisfied demand.

    Checks if any active flag points to an uncalled tool.  If no flags
    are active, checks if any uncalled tool's demand type aligns with
    the active_demand's primary_demand.

    No object_type fallback — that would drag a pure technical question
    back to catalog just because the object is a product.
    """
    # Try flag-based suggestion first
    unsatisfied = _find_unsatisfied_demand(context, called_tools)
    if unsatisfied and unsatisfied.suggest_tool:
        return unsatisfied.suggest_tool

    # Demand-type fallback: find an uncalled tool whose declared flags
    # belong to the same demand family as active_demand.primary_demand.
    if context.active_demand is None:
        return ""

    from src.ingestion.demand_profile import FLAG_DEMAND

    target_demand = context.active_demand.primary_demand
    if target_demand == "general":
        return ""

    for entry in list_registry_entries():
        cap = entry.capability
        if cap is None or cap.tool_name in called_tools:
            continue
        tool_demands = {FLAG_DEMAND.get(f, "general") for f in cap.supported_request_flags}
        if target_demand in tool_demands:
            return cap.tool_name

    return ""


def _has_meaningful_data(call: ExecutedToolCall) -> bool:
    """Check if a tool call returned non-trivial data."""
    result = call.result
    if result is None:
        return False
    return bool(result.primary_records or result.structured_facts or result.unstructured_snippets)
