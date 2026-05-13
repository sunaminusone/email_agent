"""Executor: select → dispatch → evaluate → retry loop.

The core agent behavior: select tools, dispatch, observe results,
evaluate completeness, and retry with fallback if results are insufficient.

Cross-group deduplication and observation sharing are handled via
ToolCallCache, which is passed in from the agent loop in service.py.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.common.models import DemandProfile, GroupDemand, IntentGroup
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
    active_demand: GroupDemand | None = None,
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
        active_demand=active_demand,
    )

    all_calls: list[ExecutedToolCall] = []
    # Seed `already_called` with what other groups have already done for our
    # primary object. Without this, turn-level invariants in select_tools
    # (known-catalog) and overlapping flag-driven selections re-select tools
    # every group, the dispatcher hits the cache, and each group accrues a
    # 0ms duplicate ExecutedToolCall — which then surfaces as N x duplicate
    # planned_actions.
    obj_type_for_seed = context.primary_object.object_type if context.primary_object else ""
    obj_id_for_seed = context.primary_object.identifier if context.primary_object else ""
    cross_group_satisfied: set[str] = (
        tool_call_cache.cached_for_object(obj_type_for_seed, obj_id_for_seed)
        if tool_call_cache is not None
        else set()
    )
    already_called: set[str] = set(cross_group_satisfied)
    call_counter = 0
    iteration_count = 0

    for iteration in range(MAX_ITERATIONS):
        iteration_count += 1
        # 1. SELECT — skip tools already called this turn (in this group's
        #    iterations OR by a prior group for the same object). On retry,
        #    `force_include` can override the skip.
        force_include = ""
        if iteration > 0:
            prev_eval = evaluate_completeness(context, all_calls, iteration - 1, MAX_ITERATIONS)
            force_include = prev_eval.suggest_tool

        selections = select_tools(
            context,
            already_called=already_called,
            force_include=force_include,
        )

        if not selections:
            if all_calls:
                break
            # Distinguish "satisfied by a prior group" from "no match at all":
            # if the cross-group seed is non-empty, this group's needs were
            # already covered upstream, so report ok with no calls of our
            # own (downstream merger reads the prior group's calls). Without
            # this branch _run_group_execution would treat empty as
            # needs_clarification and trigger a spurious clarify.
            if cross_group_satisfied:
                return ExecutionResult(
                    final_status="ok",
                    reason="All required tools already executed by a prior intent group.",
                    iteration_count=iteration_count,
                )
            return ExecutionResult(
                final_status="empty",
                reason="No tools matched the current context.",
                iteration_count=iteration_count,
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

    return _build_execution_result(all_calls, iteration_count=iteration_count)


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------

def _resolve_follow_up_intent(
    parser_intent: str,
    memory_snapshot: MemorySnapshot | None,
) -> str:
    """Substitute prior turn's meaningful intent when this turn is follow_up.

    follow_up is a dialogue-act label, not a retrieval bucket. Without
    substitution, RAG sees the placeholder follow_up bucket and loses the
    section-type boosts the prior topic deserves (backlog #8).
    """
    if parser_intent != "follow_up" or memory_snapshot is None:
        return parser_intent
    prior = memory_snapshot.intent_memory.prior_semantic_intent
    if prior and prior not in {"follow_up", "unknown"}:
        return prior
    return parser_intent


def build_execution_context(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    route_decision: RouteDecision,
    memory_snapshot: MemorySnapshot | None = None,
    focus_group: IntentGroup | None = None,
    demand_profile: DemandProfile | None = None,
    tool_call_cache: ToolCallCache | None = None,
    active_demand: GroupDemand | None = None,
) -> ExecutionContext:
    """Map upstream inputs into the executor's internal state.

    *active_demand* must be pre-computed by the caller and passed in
    directly.  This ensures the executor sees the exact same GroupDemand
    that routing used — no silent re-derivation.

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

    # Ambiguous aggregation: when primary is unresolved but all ambiguous
    # candidates share a single business_line, promote it so RAG can apply
    # a Layer-1 soft boost without waiting for clarification.
    if "business_line" not in constraints and resolved_object_state.ambiguous_sets:
        ambiguous_lines = {
            candidate.business_line
            for ambiguous_set in resolved_object_state.ambiguous_sets
            for candidate in ambiguous_set.candidates
            if candidate.business_line
        }
        if len(ambiguous_lines) == 1:
            constraints["business_line"] = next(iter(ambiguous_lines))

    parser_signals = ingestion_bundle.turn_signals.parser_signals

    return ExecutionContext(
        query=(
            ingestion_bundle.turn_core.normalized_query
            or ingestion_bundle.turn_core.raw_query
        ),
        semantic_intent=_resolve_follow_up_intent(
            parser_signals.context.semantic_intent,
            memory_snapshot,
        ),
        primary_object=primary,
        secondary_objects=list(resolved_object_state.secondary_objects),
        dialogue_act=route_decision.dialogue_act,
        resolved_object_constraints=constraints,
        memory_snapshot=memory_snapshot,
        request_flags=request_flags,
        retrieval_hints=parser_signals.retrieval_hints,
        parser_constraints=parser_signals.constraints,
        parser_open_slots=parser_signals.open_slots,
        demand_profile=demand_profile,
        active_demand=active_demand,
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

def _build_execution_result(
    executed_calls: list[ExecutedToolCall],
    *,
    iteration_count: int,
) -> ExecutionResult:
    """Build the final ExecutionResult from executed tool calls."""
    merged, final_status, reason = merge_execution_results(executed_calls)

    return ExecutionResult(
        executed_calls=list(executed_calls),
        merged_results=merged,
        final_status=final_status,
        reason=reason,
        iteration_count=iteration_count,
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


# ---------------------------------------------------------------------------
# Available params extraction (four-layer sources)
# ---------------------------------------------------------------------------

# Semantic mapping from object_type to param name for identifiers
_IDENTIFIER_MAPPING: dict[str, str] = {
    "order": "order_number",
    "invoice": "invoice_number",
    "shipment": "tracking_number",
    "customer": "customer_identifier",
    "product": "catalog_number",
}


def extract_available_params(
    context: ExecutionContext,
    *,
    tool_call_cache: ToolCallCache | None = None,
) -> dict[str, str]:
    """Extract all available params from four layers of sources.

    Layer 1: primary_object + secondary_objects fields
    Layer 2: resolved_object_constraints
    Layer 3: memory_snapshot
    Layer 4: cross-group tool_call_cache observations

    Lower layers use setdefault to not override higher-priority sources.
    """
    params: dict[str, str] = {}

    # --- Layer 1: primary_object ---
    obj = context.primary_object
    if obj is not None:
        if obj.identifier:
            params["identifier"] = obj.identifier
            semantic = _IDENTIFIER_MAPPING.get(obj.object_type, "")
            if semantic:
                params[semantic] = obj.identifier
        if obj.canonical_value:
            params["canonical_value"] = obj.canonical_value
        if obj.display_name:
            params["display_name"] = obj.display_name
        if obj.business_line:
            params["business_line"] = obj.business_line

    # --- Layer 1b: secondary_objects ---
    for sec_obj in context.secondary_objects:
        if sec_obj.object_type == "customer":
            if sec_obj.identifier:
                params.setdefault("customer_identifier", sec_obj.identifier)
            if sec_obj.display_name:
                params.setdefault("customer_name", sec_obj.display_name)

    # --- Layer 2: resolved_object_constraints ---
    for key, value in context.resolved_object_constraints.items():
        if value and value.strip():
            params.setdefault(key, value)

    # --- Layer 3: memory_snapshot ---
    snapshot = context.memory_snapshot
    if snapshot is not None:
        _extract_from_memory(params, snapshot)

    # --- Layer 4: cross-group observations ---
    if tool_call_cache is not None:
        obs = tool_call_cache.observations
        for key in ("product_name", "service_name", "business_line",
                     "customer_name", "order_number"):
            if obs.get(key):
                params.setdefault(key, obs[key])

    return params


def _extract_from_memory(params: dict[str, str], snapshot: MemorySnapshot) -> None:
    """Extract params from MemorySnapshot (Layer 3, lower priority)."""
    active = snapshot.object_memory.active_object
    if active is not None:
        if active.identifier:
            params.setdefault("identifier", active.identifier)
            semantic = _IDENTIFIER_MAPPING.get(active.object_type, "")
            if semantic:
                params.setdefault(semantic, active.identifier)
        if active.display_name:
            params.setdefault("display_name", active.display_name)
        if active.business_line:
            params.setdefault("business_line", active.business_line)

    for recent in snapshot.object_memory.recent_objects:
        if recent.object_type == "customer":
            if recent.identifier:
                params.setdefault("customer_identifier", recent.identifier)
            if recent.display_name:
                params.setdefault("customer_name", recent.display_name)

    for tool_result in snapshot.response_memory.last_tool_results:
        for key in ("customer_name", "order_number", "email",
                     "invoice_number", "tracking_number"):
            val = tool_result.get(key)
            if val and isinstance(val, str) and val.strip():
                params.setdefault(key, val)

    if snapshot.thread_memory.active_business_line:
        params.setdefault("business_line", snapshot.thread_memory.active_business_line)
