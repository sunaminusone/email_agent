"""Demand-aware tool selection.

Chooses tools based on the user's information needs (demand), not merely
on object type or retrieval modality.

Selection priority:
1. active_demand.request_flags — the strongest signal; each flag maps
   directly to tool capabilities.
2. ToolCapability.supported_demands — explicit declaration of which
   demand family a tool serves.
3. object_type — provides context (product, service, order) but does NOT
   determine demand on its own.

Key rule: only produce a multi-tool (hybrid) selection when the demand
is genuinely mixed (e.g. needs_protocol + needs_price).  A pure
technical question about a product should select RAG only, never catalog.

DemandProfile / GroupDemand is the single source of truth for demand
classification.  This module reads from it — it does NOT re-classify
from raw flags.
"""
from __future__ import annotations

from src.common.models import DemandType
from src.executor.models import ExecutionContext, ToolSelection
from src.ingestion.demand_profile import is_truly_mixed
from src.tools.models import ToolCapability
from src.tools.registry import list_registry_entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_tools(
    context: ExecutionContext,
    *,
    already_called: set[str] | None = None,
    force_include: str = "",
) -> list[ToolSelection]:
    """Select tools based on the user's information demand.

    Returns a list of ToolSelection ordered by match_score (descending).
    """
    already_called = already_called or set()
    capabilities = _load_capabilities()
    if not capabilities:
        return []

    demand = _classify_demand(context)
    active_flags = _get_active_flags(context)

    # Score all tools against demand
    scored: list[tuple[ToolCapability, float, list[str]]] = []
    for cap in capabilities:
        score, reasons = _score_tool(cap, context, demand, active_flags)
        scored.append((cap, score, reasons))
    scored.sort(key=lambda x: -x[1])

    # --- Build selection ---
    selected: dict[str, ToolSelection] = {}

    # 0. Force-include (retry/fallback)
    if force_include:
        for cap, score, reasons in scored:
            if cap.tool_name == force_include:
                selected[cap.tool_name] = ToolSelection(
                    tool_name=cap.tool_name,
                    match_score=round(max(score, 0.3), 4),
                    match_reasons=[*reasons, "force_included_by_retry"],
                    role="primary" if not selected else "supporting",
                    can_run_in_parallel=cap.can_run_in_parallel,
                )
                break

    # 1. Primary tool — always use base threshold (0.3).
    #    Confidence does NOT suppress primary selection.
    if not selected:
        for cap, score, reasons in scored:
            if score < 0.3:
                break
            if cap.tool_name in already_called:
                continue
            selected[cap.tool_name] = ToolSelection(
                tool_name=cap.tool_name,
                match_score=round(score, 4),
                match_reasons=reasons,
                role="primary",
                can_run_in_parallel=cap.can_run_in_parallel,
            )
            break

    # 2. Supporting tools — ONLY when demand is truly mixed and flags
    #    explicitly require a tool that the primary doesn't cover.
    #    Low confidence raises the bar for adding supporting tools.
    confidence = context.active_demand.demand_confidence if context.active_demand else 1.0
    supporting_min_score = 0.5 if confidence < 0.5 else 0.3

    if demand == "mixed" and active_flags:
        primary_tool = next(iter(selected), "")
        primary_flags_covered = set()
        for cap, _, _ in scored:
            if cap.tool_name == primary_tool:
                primary_flags_covered = set(cap.supported_request_flags)
                break

        uncovered_flags = active_flags - primary_flags_covered
        if uncovered_flags:
            for cap, score, reasons in scored:
                if cap.tool_name in selected or cap.tool_name in already_called:
                    continue
                if score < supporting_min_score:
                    continue
                # Only add if this tool covers an uncovered flag
                tool_flags = set(cap.supported_request_flags)
                if tool_flags & uncovered_flags:
                    selected[cap.tool_name] = ToolSelection(
                        tool_name=cap.tool_name,
                        match_score=round(score, 4),
                        match_reasons=[*reasons, f"covers_uncovered_demand({tool_flags & uncovered_flags})"],
                        role="supporting",
                        can_run_in_parallel=cap.can_run_in_parallel,
                    )
                    uncovered_flags -= tool_flags

    # 3. CSR mode invariant: both retrieval tools always run, regardless of
    #    whether the primary classification "matched" them. Their value is
    #    complementary: historical_thread_tool surfaces past similar
    #    inquiries with how sales actually replied; technical_rag_tool
    #    surfaces relevant KB chunks (service flyers, workflow docs).
    #    The CSR sees both and decides what to use.
    #
    #    These are turn-level invariants — every CSR turn benefits from
    #    them. The `already_called` set passed by run_executor is seeded
    #    with cross-group cache hits, so when a prior group already ran
    #    these for the same object we skip here and avoid duplicate 0ms
    #    cache-hit entries in this group's executed_calls.
    CSR_ALWAYS_INCLUDE = ("historical_thread_tool", "technical_rag_tool")
    for tool_name in CSR_ALWAYS_INCLUDE:
        if tool_name in selected or tool_name in already_called:
            continue
        for cap, score, reasons in scored:
            if cap.tool_name != tool_name:
                continue
            selected[tool_name] = ToolSelection(
                tool_name=tool_name,
                match_score=round(max(score, 0.3), 4),
                match_reasons=[*reasons, "csr_mode_always_include"],
                role="supporting",
                can_run_in_parallel=cap.can_run_in_parallel,
            )
            break

    # 4. Known-catalog invariant: when the customer pinned the inquiry to a
    #    real catalog product (registry-resolved catalog_no), always include
    #    catalog_lookup_tool as supporting. The CSR needs structured product
    #    specs to ground the reply, even when the primary demand is technical
    #    (datasheet/sequence questions) rather than commercial.
    if (
        "catalog_lookup_tool" not in selected
        and "catalog_lookup_tool" not in already_called
        and _has_known_catalog_product(context)
    ):
        for cap, score, reasons in scored:
            if cap.tool_name != "catalog_lookup_tool":
                continue
            selected["catalog_lookup_tool"] = ToolSelection(
                tool_name="catalog_lookup_tool",
                match_score=round(max(score, 0.3), 4),
                match_reasons=[*reasons, "known_catalog_product_invariant"],
                role="supporting",
                can_run_in_parallel=cap.can_run_in_parallel,
            )
            break

    result = list(selected.values())
    result.sort(key=lambda s: (-s.match_score, s.role != "primary"))
    return result


# ---------------------------------------------------------------------------
# Demand classification — reads GroupDemand, no re-computation
# ---------------------------------------------------------------------------

def _classify_demand(context: ExecutionContext) -> DemandType:
    """Classify the user's information demand from the pre-computed GroupDemand.

    GroupDemand (via active_demand) is the single source of truth.
    No fallback to raw flags or semantic_intent — if active_demand is
    absent the executor treats the demand as general (conservative).

    Low demand_confidence (< 0.5) suppresses mixed classification —
    the executor stays conservative and commits to the primary demand
    only, avoiding speculative multi-tool expansion.
    """
    if context.active_demand is None:
        return "general"

    ad = context.active_demand
    if (
        ad.demand_confidence >= 0.5
        and is_truly_mixed(ad.primary_demand, ad.secondary_demands)
    ):
        return "mixed"
    return ad.primary_demand


def _get_active_flags(context: ExecutionContext) -> set[str]:
    """Return the set of active flag names from active_demand.

    No fallback to raw request_flags — GroupDemand is the single source.
    """
    if context.active_demand is None:
        return set()
    return set(context.active_demand.request_flags)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_tool(
    capability: ToolCapability,
    context: ExecutionContext,
    demand: DemandType,
    active_flags: set[str],
) -> tuple[float, list[str]]:
    """Score a tool against the current demand.

    Weight hierarchy:
    - Flag match:          0.35 per matched flag (demand signal)
    - Demand alignment:    0.25 (tool explicitly declares the right demand type)
    - Object type match:   0.20 + specialization tiebreaker
    - Dialogue act match:  0.10
    """
    score = 0.0
    reasons: list[str] = []

    # --- Flag match (strongest: directly demanded) ---
    tool_flags = set(capability.supported_request_flags)
    matched_flags = tool_flags & active_flags
    if matched_flags:
        flag_score = min(len(matched_flags) * 0.35, 0.70)
        score += flag_score
        reasons.append(f"flag_match={matched_flags}")

    # --- Demand alignment (tool's declared purpose matches demand type) ---
    if demand != "general":
        tool_demand_types = _tool_demand_types(capability)
        if demand in tool_demand_types or (demand == "mixed" and tool_demand_types - {"general"}):
            score += 0.25
            reasons.append(f"demand_aligned={demand}")
        elif not tool_flags and _tool_aligns_with_demand(capability, demand):
            score += 0.15
            reasons.append(f"implicit_demand_aligned={demand}")

    # --- Object type match (context, not demand) ---
    if context.primary_object is not None:
        if context.primary_object.object_type in capability.supported_object_types:
            score += 0.20
            reasons.append(f"object_type={context.primary_object.object_type}")
            idx = capability.supported_object_types.index(context.primary_object.object_type)
            score += round(0.01 / (idx + 1), 4)

    # --- Secondary object match (0.05 each, capped at 0.1) ---
    secondary_bonus = 0.0
    for obj in context.secondary_objects:
        if obj.object_type in capability.supported_object_types:
            secondary_bonus += 0.05
    secondary_bonus = min(secondary_bonus, 0.1)
    if secondary_bonus > 0:
        score += secondary_bonus
        reasons.append(f"secondary_objects(+{secondary_bonus})")

    # --- Dialogue act match ---
    if context.dialogue_act.act in capability.supported_dialogue_acts:
        score += 0.10
        reasons.append(f"dialogue_act={context.dialogue_act.act}")

    return score, reasons


def _tool_aligns_with_demand(capability: ToolCapability, demand: DemandType) -> bool:
    """Heuristic: does a tool without explicit flag declarations align with the demand?"""
    modalities = set(capability.supported_modalities)
    if demand == "technical":
        return bool(modalities & {"unstructured_retrieval", "hybrid"})
    if demand == "commercial":
        return bool(modalities & {"structured_lookup", "hybrid"})
    if demand == "operational":
        return bool(modalities & {"external_api"})
    return False


def _tool_demand_types(capability: ToolCapability) -> set[DemandType]:
    """Return the demand families a tool can serve.

    ToolCapability.supported_demands is the contract here. Selector
    should not re-derive demand families from request flags.
    """
    return {
        demand
        for demand in capability.supported_demands
        if demand != "general"
    }


# ---------------------------------------------------------------------------
# Registry reading
# ---------------------------------------------------------------------------

def _load_capabilities() -> list[ToolCapability]:
    """Read all ToolCapability declarations from the tool registry."""
    caps: list[ToolCapability] = []
    for entry in list_registry_entries():
        if entry.capability is not None:
            caps.append(entry.capability)
    return caps


def _has_known_catalog_product(context: ExecutionContext) -> bool:
    po = context.primary_object
    if po is None or po.object_type != "product" or po.identifier_type != "catalog_no":
        return False
    metadata = po.metadata if isinstance(po.metadata, dict) else {}
    return metadata.get("match_strategy") != "unknown_catalog_no"
