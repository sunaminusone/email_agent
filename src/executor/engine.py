"""Executor: select → dispatch → evaluate → retry loop.

The core agent behavior: select tools, dispatch, observe results,
evaluate completeness, and retry with fallback if results are insufficient.

Cross-group deduplication and observation sharing are handled via
ToolCallCache, which is passed in from the agent loop in service.py.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.common.models import DemandProfile, IntentGroup
from src.executor.completeness import evaluate_completeness
from src.executor.merger import merge_execution_results
from src.executor.models import (
    ExecutedToolCall,
    ExecutionContext,
    ExecutionResult,
    ToolSelection,
)
from src.executor.request_builder import build_tool_request
from src.executor.tool_selector import select_tools
from src.ingestion.demand_profile import narrow_demand_profile
from src.ingestion.models import IngestionBundle, ParserRequestFlags
from src.memory.models import MemorySnapshot
from src.objects.models import ObjectCandidate, ResolvedObjectState
from src.routing.models import RouteDecision
from src.tools.dispatcher import safe_dispatch_tool

if TYPE_CHECKING:
    from src.agent.tool_call_cache import ToolCallCache


MAX_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_executor(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    route_decision: RouteDecision,
    memory_snapshot: MemorySnapshot | None = None,
    *,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
    tool_call_cache: ToolCallCache | None = None,
) -> ExecutionResult:
    """Run the executor with evaluate → retry loop.

    When *tool_call_cache* is provided:
    - Before dispatching, check if the same tool+object was already called
      by a prior group.  If so, reuse the cached result (deduplication).
    - After dispatching, store results in the cache so subsequent groups
      can reuse them.
    - Enrich tool requests with cross-group observations (e.g., a product
      name discovered by a prior group's catalog call).
    """
    context = build_execution_context(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved_object_state,
        route_decision=route_decision,
        memory_snapshot=memory_snapshot,
        focus_group=focus_group,
        demand_profile=demand_profile,
        tool_call_cache=tool_call_cache,
    )

    all_calls: list[ExecutedToolCall] = []
    already_called: set[str] = set()
    call_counter = 0

    for iteration in range(MAX_ITERATIONS):
        # 1. SELECT — on retry, skip already-called tools (unless force_include)
        force_include = ""
        if iteration > 0:
            prev_eval = evaluate_completeness(context, all_calls, iteration - 1, MAX_ITERATIONS)
            force_include = prev_eval.suggest_tool

        selections = select_tools(
            context,
            already_called=already_called if iteration > 0 else None,
            force_include=force_include,
        )

        if not selections:
            if all_calls:
                break
            return ExecutionResult(
                final_status="empty",
                reason="No tools matched the current context.",
            )

        # 2. DISPATCH (with cache dedup)
        obj_type = context.primary_object.object_type if context.primary_object else ""
        obj_id = context.primary_object.identifier if context.primary_object else ""

        new_calls = _dispatch_selections(
            context, selections, call_offset=call_counter,
            tool_call_cache=tool_call_cache, object_type=obj_type, object_identifier=obj_id,
        )
        all_calls.extend(new_calls)
        call_counter += len(new_calls)
        already_called.update(call.tool_name for call in new_calls)

        # 3. EVALUATE
        completeness = evaluate_completeness(context, all_calls, iteration, MAX_ITERATIONS)

        if completeness.verdict == "sufficient":
            break
        if completeness.verdict in ("done_partial", "done_empty", "done_error"):
            break
        # retry_with_fallback or retry_add_tool → continue loop

    return _build_execution_result(all_calls)


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------

def build_execution_context(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    route_decision: RouteDecision,
    memory_snapshot: MemorySnapshot | None = None,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
    tool_call_cache: ToolCallCache | None = None,
) -> ExecutionContext:
    """Map upstream inputs into the executor's internal state.

    When *tool_call_cache* carries observations from prior groups,
    enrich the resolved_object_constraints with discovered names
    so downstream tool requests (e.g., RAG scope) benefit.
    """
    primary = resolved_object_state.primary_object
    request_flags = ingestion_bundle.turn_signals.parser_signals.request_flags

    if focus_group is not None:
        request_flags = _narrow_request_flags(request_flags, focus_group)

    constraints = _extract_object_constraints(primary)

    # Cross-group observation: enrich constraints with facts discovered by prior groups
    if tool_call_cache is not None:
        obs = tool_call_cache.observations
        if obs.get("product_name") and "display_name" not in constraints:
            constraints.setdefault("display_name", obs["product_name"])
        if obs.get("service_name") and "display_name" not in constraints:
            constraints.setdefault("display_name", obs["service_name"])
        if obs.get("business_line") and "business_line" not in constraints:
            constraints.setdefault("business_line", obs["business_line"])

    return ExecutionContext(
        query=(
            ingestion_bundle.turn_core.normalized_query
            or ingestion_bundle.turn_core.raw_query
        ),
        primary_intent=ingestion_bundle.turn_signals.parser_signals.context.primary_intent,
        primary_object=primary,
        secondary_objects=list(resolved_object_state.secondary_objects),
        dialogue_act=route_decision.dialogue_act,
        resolved_object_constraints=constraints,
        memory_snapshot=memory_snapshot,
        request_flags=request_flags,
        retrieval_hints=ingestion_bundle.turn_signals.parser_signals.retrieval_hints,
        demand_profile=demand_profile,
        active_demand=narrow_demand_profile(demand_profile, focus_group),
    )


def _narrow_request_flags(
    original: ParserRequestFlags,
    focus_group: IntentGroup,
) -> ParserRequestFlags:
    """Create a copy of request_flags with only the flags in focus_group active."""
    if not focus_group.request_flags:
        return original

    narrowed_data: dict[str, bool] = {}
    for field_name in ParserRequestFlags.model_fields:
        narrowed_data[field_name] = field_name in focus_group.request_flags

    return ParserRequestFlags.model_validate(narrowed_data)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch_selections(
    context: ExecutionContext,
    selections: list[ToolSelection],
    call_offset: int = 0,
    *,
    tool_call_cache: ToolCallCache | None = None,
    object_type: str = "",
    object_identifier: str = "",
) -> list[ExecutedToolCall]:
    """Build requests and dispatch tools for a set of selections.

    Before dispatching, checks the cross-group cache for a reusable result.
    After dispatching, stores the result in the cache.
    """
    executed: list[ExecutedToolCall] = []
    selected_tool_names = [s.tool_name for s in selections]

    for idx, selection in enumerate(selections, start=call_offset + 1):
        # Check cache: has another group already called this tool for the same object?
        cached = (
            tool_call_cache.get_cached(selection.tool_name, object_type, object_identifier)
            if tool_call_cache is not None
            else None
        )

        if cached is not None:
            # Reuse the cached result — reassign call_id and role for this group
            reused = ExecutedToolCall(
                call_id=f"call{idx}",
                tool_name=cached.tool_name,
                role=selection.role,
                status=cached.status,
                request=cached.request,
                result=cached.result,
                latency_ms=0,
                error=cached.error,
            )
            executed.append(reused)
            continue

        # No cache hit — dispatch normally
        request = build_tool_request(
            context, selection.tool_name, selected_tools=selected_tool_names,
        )

        started = time.perf_counter()
        result = safe_dispatch_tool(request)
        latency_ms = int((time.perf_counter() - started) * 1000)

        call = ExecutedToolCall(
            call_id=f"call{idx}",
            tool_name=selection.tool_name,
            role=selection.role,
            status=result.status,
            request=request,
            result=result,
            latency_ms=latency_ms,
            error=result.errors[0] if result.errors else "",
        )
        executed.append(call)

        # Store in cache for future groups
        if tool_call_cache is not None:
            tool_call_cache.store(call, object_type, object_identifier)

    return executed


# ---------------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------------

def _build_execution_result(executed_calls: list[ExecutedToolCall]) -> ExecutionResult:
    """Build the final ExecutionResult from executed tool calls."""
    merged, final_status, reason = merge_execution_results(executed_calls)

    return ExecutionResult(
        executed_calls=list(executed_calls),
        merged_results=merged,
        final_status=final_status,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_object_constraints(primary: ObjectCandidate | None) -> dict[str, str]:
    if primary is None:
        return {}
    constraints: dict[str, str] = {
        "object_type": primary.object_type,
        "canonical_value": primary.canonical_value,
        "display_name": primary.display_name,
        "identifier": primary.identifier,
        "identifier_type": primary.identifier_type,
        "business_line": primary.business_line,
    }
    return {k: v for k, v in constraints.items() if v}
