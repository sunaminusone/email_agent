from __future__ import annotations

from src.common.models import DemandProfile, DemandType, GroupDemand, IntentGroup
from src.ingestion.models import ParserRequestFlags, ParserSignals


INTENT_DEMAND: dict[str, DemandType] = {
    "technical_question": "technical",
    "troubleshooting": "technical",
    "documentation_request": "technical",
    "product_inquiry": "commercial",
    "pricing_question": "commercial",
    "timeline_question": "commercial",
    "customization_request": "commercial",
    "order_support": "operational",
    "shipping_question": "operational",
    "complaint": "operational",
    "follow_up": "general",
    "general_info": "general",
    "partnership_request": "general",
    "unknown": "general",
}

FLAG_DEMAND: dict[str, DemandType] = {
    "needs_protocol": "technical",
    "needs_troubleshooting": "technical",
    "needs_recommendation": "technical",
    "needs_regulatory_info": "technical",
    "needs_documentation": "technical",
    "needs_price": "commercial",
    "needs_quote": "commercial",
    "needs_availability": "commercial",
    "needs_comparison": "commercial",
    "needs_sample": "commercial",
    "needs_timeline": "commercial",
    "needs_customization": "commercial",
    "needs_order_status": "operational",
    "needs_shipping_info": "operational",
    "needs_invoice": "operational",
    "needs_refund_or_cancellation": "operational",
}


def build_demand_profile(
    parser_signals: ParserSignals,
    intent_groups: list[IntentGroup],
    *,
    prior_demand_type: str = "general",
    prior_demand_flags: list[str] | None = None,
    continuity_confidence: float = 0.0,
) -> DemandProfile:
    """Build a shared semantic demand contract from parser output + intent groups.

    When prior demand context is available (from MemoryContext), weak
    follow-up groups may inherit the prior demand lane and flags, while
    matching groups receive a confidence boost.
    """
    active_flags = _active_flags(parser_signals.request_flags)
    intent_hint = parser_signals.context.primary_intent
    primary_demand, secondary_demands = _resolve_demands(
        active_flags,
        intent_hint=intent_hint,
    )

    group_demands = [
        build_group_demand(
            group,
            prior_demand_type=prior_demand_type,
            prior_demand_flags=prior_demand_flags,
            continuity_confidence=continuity_confidence,
        )
        for group in intent_groups
    ]

    reason_parts = [
        f"intent={intent_hint}",
        f"flags={','.join(active_flags) if active_flags else 'none'}",
        f"groups={len(group_demands)}",
    ]
    if prior_demand_type != "general" and continuity_confidence > 0:
        reason_parts.append(f"prior={prior_demand_type}(cont={continuity_confidence:.2f})")

    return DemandProfile(
        primary_demand=primary_demand,
        secondary_demands=secondary_demands,
        active_request_flags=active_flags,
        group_demands=group_demands,
        reason="; ".join(reason_parts),
    )


def build_group_demand(
    group: IntentGroup,
    *,
    prior_demand_type: str = "general",
    prior_demand_flags: list[str] | None = None,
    continuity_confidence: float = 0.0,
) -> GroupDemand:
    primary_demand, secondary_demands = _resolve_demands(
        group.request_flags,
        intent_hint=group.intent,
    )
    base_confidence = _compute_demand_confidence(group.request_flags, group.intent)
    effective_flags = list(group.request_flags)
    prior_demand_flags = list(prior_demand_flags or [])

    # Demand inheritance: when this turn's signals are too weak to classify
    # (general) but the conversation is clearly continuing in a prior
    # demand lane (high continuity), inherit the prior demand type and
    # carry forward the prior demand flags as semantic hints.
    # This handles follow-ups like "那个呢？" or "tell me more".
    if (
        primary_demand == "general"
        and prior_demand_type != "general"
        and prior_demand_flags
        and continuity_confidence >= 0.7
        and group.intent in {"unknown", "follow_up", "general_info"}
    ):
        primary_demand = prior_demand_type
        effective_flags = list(prior_demand_flags)
        base_confidence = 0.6  # inherited, not directly observed
    # Continuity boost: if this group's demand matches the prior turn's
    # demand AND the conversation is continuing (continuity > 0), nudge
    # confidence up.  A follow-up in the same demand lane is more
    # certain than a cold start.
    elif (
        prior_demand_type != "general"
        and continuity_confidence > 0
        and primary_demand == prior_demand_type
        and base_confidence < 0.9  # don't boost already-strong signals
    ):
        boost = min(continuity_confidence * 0.2, 0.2)
        base_confidence = min(base_confidence + boost, 0.9)

    return GroupDemand(
        intent=group.intent,
        primary_demand=primary_demand,
        secondary_demands=secondary_demands,
        request_flags=effective_flags,
        object_type=group.object_type,
        object_identifier=group.object_identifier,
        object_display_name=group.object_display_name,
        demand_confidence=base_confidence,
    )


def _compute_demand_confidence(flags: list[str], intent: str) -> float:
    """Demand confidence from signal strength, NOT from object binding.

    - Flags active → 0.9 (explicit demand signal)
    - No flags, intent maps non-general → 0.7 (inferred from intent)
    - No flags, general/unknown intent → 0.4 (weak signal)
    """
    non_general_flags = [f for f in flags if FLAG_DEMAND.get(f, "general") != "general"]
    if non_general_flags:
        return 0.9
    if INTENT_DEMAND.get(intent, "general") != "general":
        return 0.7
    return 0.4


def narrow_demand_profile(
    demand_profile: DemandProfile | None,
    focus_group: IntentGroup | None,
) -> GroupDemand | None:
    """Return the demand scoped to a focus group, preserving shared semantics."""
    if focus_group is None:
        return None
    if demand_profile is not None:
        matched = _match_group_demand(demand_profile.group_demands, focus_group)
        if matched is not None:
            return matched
    return build_group_demand(focus_group)


def is_truly_mixed(primary: DemandType, secondaries: list[DemandType]) -> bool:
    """Check if demands actually span different families (ignoring 'general').

    secondary_demands existing doesn't automatically mean mixed — e.g.
    primary='technical' + secondary=['general'] is just technical.
    Only return True when there are ≥2 distinct non-general demand types.
    """
    real_demands = {primary} | set(secondaries)
    real_demands.discard("general")
    return len(real_demands) > 1


def _resolve_demands(
    active_flags: list[str],
    *,
    intent_hint: str,
) -> tuple[DemandType, list[DemandType]]:
    flag_demands = _dedupe_demands(
        FLAG_DEMAND.get(flag_name, "general")
        for flag_name in active_flags
    )
    intent_demand = INTENT_DEMAND.get(intent_hint, "general")

    if not flag_demands:
        return intent_demand, []

    if intent_demand in flag_demands:
        primary_demand = intent_demand
    else:
        primary_demand = flag_demands[0]

    secondary_demands = [
        demand
        for demand in flag_demands
        if demand != primary_demand
    ]
    return primary_demand, secondary_demands


def _active_flags(request_flags: ParserRequestFlags) -> list[str]:
    return [
        field_name
        for field_name in ParserRequestFlags.model_fields
        if getattr(request_flags, field_name, False)
    ]


def _dedupe_demands(demands) -> list[DemandType]:
    deduped: list[DemandType] = []
    for demand in demands:
        if demand == "general" or demand in deduped:
            continue
        deduped.append(demand)
    return deduped


def _match_group_demand(
    group_demands: list[GroupDemand],
    focus_group: IntentGroup,
) -> GroupDemand | None:
    for group_demand in group_demands:
        if (
            group_demand.intent == focus_group.intent
            and group_demand.object_type == focus_group.object_type
            and group_demand.object_identifier == focus_group.object_identifier
            and set(group_demand.request_flags) == set(focus_group.request_flags)
        ):
            return group_demand
    return None
