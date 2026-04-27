"""Tests for the executor layer: merger, tool_selector, request_builder, engine, completeness."""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.execution_models import ExecutedToolCall, ExecutionResult, MergedResults
from src.common.models import DemandProfile, GroupDemand, IntentGroup
from src.ingestion.demand_profile import narrow_demand_profile
from src.executor.completeness import evaluate_completeness, CompletenessResult
from src.executor.merger import final_status_for_calls, merge_execution_results
from src.executor.models import ExecutionContext, ToolSelection
from src.executor.request_builder import build_tool_request
from src.executor.tool_selector import select_tools, _score_tool, _classify_demand, _get_active_flags
from src.executor.engine import _resolve_follow_up_intent, build_execution_context, run_executor
from src.ingestion.models import ParserConstraints, ParserOpenSlots, ParserRequestFlags, ParserRetrievalHints
from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult, RouteDecision
from src.tools.models import ToolCapability, ToolRequest, ToolResult
from src.tools.registry import register_tool, clear_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_result(tool_name: str, status: str = "ok", **kwargs) -> ToolResult:
    return ToolResult(tool_name=tool_name, status=status, **kwargs)


def _make_executed_call(
    tool_name: str,
    status: str = "ok",
    role: str = "primary",
    result: ToolResult | None = None,
) -> ExecutedToolCall:
    return ExecutedToolCall(
        call_id="c1",
        tool_name=tool_name,
        role=role,
        status=status,
        request=ToolRequest(tool_name=tool_name, query="test"),
        result=result or _make_tool_result(tool_name, status),
    )


def _make_context(
    query: str = "test query",
    object_type: str = "product",
    dialogue_act: str = "inquiry",
    request_flags: ParserRequestFlags | None = None,
    semantic_intent: str = "product_inquiry",
    parser_constraints: ParserConstraints | None = None,
    parser_open_slots: ParserOpenSlots | None = None,
) -> ExecutionContext:
    primary = ObjectCandidate(
        object_type=object_type,
        canonical_value="Test Product",
        display_name="Test Product",
        identifier="TP-001",
        identifier_type="catalog_no",
        business_line="reagents",
    ) if object_type else None
    return ExecutionContext(
        query=query,
        semantic_intent=semantic_intent,
        primary_object=primary,
        dialogue_act=DialogueActResult(act=dialogue_act),
        request_flags=request_flags,
        parser_constraints=parser_constraints,
        parser_open_slots=parser_open_slots,
    )


# ===================================================================
# merger tests
# ===================================================================

class TestFinalStatusForCalls:

    def test_empty_list_returns_empty(self) -> None:
        assert final_status_for_calls([]) == "empty"

    def test_all_ok_returns_ok(self) -> None:
        assert final_status_for_calls(["ok", "ok"]) == "ok"

    def test_any_error_returns_error(self) -> None:
        assert final_status_for_calls(["ok", "error"]) == "error"

    def test_partial_without_error_returns_partial(self) -> None:
        assert final_status_for_calls(["ok", "partial"]) == "partial"

    def test_all_empty_returns_empty(self) -> None:
        assert final_status_for_calls(["empty", "empty"]) == "empty"

    def test_error_takes_precedence_over_partial(self) -> None:
        assert final_status_for_calls(["partial", "error", "ok"]) == "error"


class TestMergeExecutionResults:

    def test_merges_primary_and_supporting_facts(self) -> None:
        calls = [
            _make_executed_call(
                "catalog_lookup_tool", role="primary",
                result=_make_tool_result(
                    "catalog_lookup_tool",
                    structured_facts={"species": ["human"]},
                ),
            ),
            _make_executed_call(
                "technical_rag_tool", role="supporting",
                result=_make_tool_result(
                    "technical_rag_tool",
                    structured_facts={"protocol": "IF"},
                ),
            ),
        ]
        merged, status, reason = merge_execution_results(calls)

        assert "catalog_lookup_tool" in merged.primary_facts
        assert "technical_rag_tool" in merged.supporting_facts
        assert status == "ok"

    def test_empty_calls_returns_empty(self) -> None:
        merged, status, reason = merge_execution_results([])
        assert status == "empty"
        assert merged.primary_facts == {}
        assert "No tool calls" in reason

    def test_collects_snippets_and_artifacts(self) -> None:
        calls = [
            _make_executed_call(
                "rag_tool", role="primary",
                result=_make_tool_result(
                    "rag_tool",
                    unstructured_snippets=[{"text": "snippet1"}],
                    artifacts=[{"file_name": "doc.pdf"}],
                ),
            ),
        ]
        merged, _, _ = merge_execution_results(calls)
        assert len(merged.snippets) == 1
        assert len(merged.artifacts) == 1

    def test_none_result_is_skipped(self) -> None:
        call = ExecutedToolCall(
            call_id="c1",
            tool_name="broken",
            status="error",
            request=ToolRequest(tool_name="broken", query="x"),
            result=None,
            error="timeout",
        )
        merged, status, _ = merge_execution_results([call])
        assert status == "error"
        assert merged.primary_facts == {}


# ===================================================================
# tool_selector tests
# ===================================================================

class TestScoreTool:

    def test_flag_match_scores_highest(self) -> None:
        """A tool matching an active flag should score higher than one matching only object_type."""
        rag_cap = ToolCapability(
            tool_name="rag_tool",
            supported_object_types=["product"],
            supported_demands=["technical"],
            supported_dialogue_acts=["inquiry"],
            supported_modalities=["unstructured_retrieval"],
            supported_request_flags=["needs_protocol"],
        )
        catalog_cap = ToolCapability(
            tool_name="catalog_tool",
            supported_object_types=["product"],
            supported_demands=["commercial"],
            supported_dialogue_acts=["inquiry"],
            supported_modalities=["structured_lookup"],
        )
        flags = ParserRequestFlags(needs_protocol=True)
        active = {"needs_protocol"}
        ctx = _make_context(object_type="product", request_flags=flags, semantic_intent="technical_question")

        rag_score, _ = _score_tool(rag_cap, ctx, "technical", active)
        catalog_score, _ = _score_tool(catalog_cap, ctx, "technical", active)
        assert rag_score > catalog_score

    def test_no_match_scores_zero(self) -> None:
        cap = ToolCapability(
            tool_name="order_tool",
            supported_object_types=["order"],
            supported_demands=["operational"],
            supported_dialogue_acts=["inquiry"],
            supported_modalities=["external_api"],
        )
        ctx = _make_context(object_type="product", dialogue_act="selection")
        score, _ = _score_tool(cap, ctx, "commercial", set())
        assert score < 0.3

    def test_demand_alignment_boosts_score(self) -> None:
        rag_cap = ToolCapability(
            tool_name="rag_tool",
            supported_object_types=["product"],
            supported_demands=["technical"],
            supported_request_flags=["needs_protocol"],
            supported_modalities=["unstructured_retrieval"],
        )
        # Technical demand → RAG aligns
        ctx_tech = _make_context(semantic_intent="technical_question")
        score_tech, _ = _score_tool(rag_cap, ctx_tech, "technical", set())

        # Commercial demand → RAG doesn't align
        ctx_comm = _make_context(semantic_intent="product_inquiry")
        score_comm, _ = _score_tool(rag_cap, ctx_comm, "commercial", set())

        assert score_tech > score_comm


class TestClassifyDemand:

    def test_technical_from_active_demand(self) -> None:
        ctx = _make_context(request_flags=ParserRequestFlags(needs_protocol=True))
        ctx.active_demand = GroupDemand(
            primary_demand="technical", request_flags=["needs_protocol"],
        )
        assert _classify_demand(ctx) == "technical"

    def test_commercial_from_active_demand(self) -> None:
        ctx = _make_context(request_flags=ParserRequestFlags(needs_price=True))
        ctx.active_demand = GroupDemand(
            primary_demand="commercial", request_flags=["needs_price"],
        )
        assert _classify_demand(ctx) == "commercial"

    def test_mixed_from_truly_different_demands(self) -> None:
        ctx = _make_context(request_flags=ParserRequestFlags(needs_protocol=True, needs_price=True))
        ctx.active_demand = GroupDemand(
            primary_demand="technical",
            secondary_demands=["commercial"],
            request_flags=["needs_protocol", "needs_price"],
            demand_confidence=0.8,
        )
        assert _classify_demand(ctx) == "mixed"

    def test_not_mixed_when_secondary_only_general(self) -> None:
        """primary=technical + secondary=[general] is NOT mixed."""
        ctx = _make_context()
        ctx.active_demand = GroupDemand(
            primary_demand="technical",
            secondary_demands=["general"],
            request_flags=["needs_protocol"],
            demand_confidence=0.8,
        )
        assert _classify_demand(ctx) == "technical"

    def test_low_confidence_suppresses_mixed(self) -> None:
        """When confidence < 0.5, truly mixed demands fall back to primary only."""
        ctx = _make_context()
        ctx.active_demand = GroupDemand(
            primary_demand="technical",
            secondary_demands=["commercial"],
            request_flags=["needs_protocol", "needs_price"],
            demand_confidence=0.3,
        )
        assert _classify_demand(ctx) == "technical"

    def test_general_when_no_active_demand(self) -> None:
        """No active_demand → conservative general, no re-classification."""
        ctx = _make_context(semantic_intent="technical_question")
        assert _classify_demand(ctx) == "general"

    def test_operational_from_active_demand(self) -> None:
        ctx = _make_context(request_flags=ParserRequestFlags(needs_order_status=True))
        ctx.active_demand = GroupDemand(
            primary_demand="operational", request_flags=["needs_order_status"],
        )
        assert _classify_demand(ctx) == "operational"


class TestSelectTools:

    def setup_method(self) -> None:
        clear_registry()

    def teardown_method(self) -> None:
        clear_registry()

    def test_selects_matching_tool(self) -> None:
        register_tool(
            tool_name="catalog_lookup_tool",
            executor=lambda req: _make_tool_result(req.tool_name),
            capability=ToolCapability(
                tool_name="catalog_lookup_tool",
                supported_object_types=["product"],
                supported_demands=["commercial"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["structured_lookup"],
            ),
        )
        context = _make_context(object_type="product", dialogue_act="inquiry")
        selections = select_tools(context)
        assert len(selections) >= 1
        assert selections[0].tool_name == "catalog_lookup_tool"
        assert selections[0].role == "primary"

    def test_returns_empty_when_no_tools_registered(self) -> None:
        context = _make_context()
        selections = select_tools(context)
        assert selections == []

    def test_pure_technical_selects_rag_only(self) -> None:
        register_tool(
            tool_name="catalog_lookup_tool",
            executor=lambda req: _make_tool_result(req.tool_name),
            capability=ToolCapability(
                tool_name="catalog_lookup_tool",
                supported_object_types=["product"],
                supported_demands=["commercial"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["structured_lookup"],
                supported_request_flags=["needs_availability"],
            ),
        )
        register_tool(
            tool_name="technical_rag_tool",
            executor=lambda req: _make_tool_result(req.tool_name),
            capability=ToolCapability(
                tool_name="technical_rag_tool",
                supported_object_types=["product"],
                supported_demands=["technical"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["unstructured_retrieval"],
                supported_request_flags=["needs_protocol"],
            ),
        )
        flags = ParserRequestFlags(needs_protocol=True)
        ctx = _make_context(
            object_type="product", dialogue_act="inquiry",
            request_flags=flags, semantic_intent="technical_question",
        )
        ctx.active_demand = GroupDemand(
            primary_demand="technical", request_flags=["needs_protocol"],
        )
        sels = select_tools(ctx)
        tool_names = [s.tool_name for s in sels]
        assert tool_names == ["technical_rag_tool"]

    def test_mixed_demand_selects_multiple_tools(self) -> None:
        register_tool(
            tool_name="pricing_lookup_tool",
            executor=lambda req: _make_tool_result(req.tool_name),
            capability=ToolCapability(
                tool_name="pricing_lookup_tool",
                supported_object_types=["product"],
                supported_demands=["commercial"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["structured_lookup"],
                supported_request_flags=["needs_price"],
            ),
        )
        register_tool(
            tool_name="technical_rag_tool",
            executor=lambda req: _make_tool_result(req.tool_name),
            capability=ToolCapability(
                tool_name="technical_rag_tool",
                supported_object_types=["product"],
                supported_demands=["technical"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["unstructured_retrieval"],
                supported_request_flags=["needs_protocol"],
            ),
        )
        flags = ParserRequestFlags(needs_protocol=True, needs_price=True)
        ctx = _make_context(
            object_type="product", dialogue_act="inquiry",
            request_flags=flags, semantic_intent="technical_question",
        )
        ctx.active_demand = GroupDemand(
            primary_demand="technical",
            secondary_demands=["commercial"],
            request_flags=["needs_protocol", "needs_price"],
            demand_confidence=0.8,
        )
        sels = select_tools(ctx)
        tool_names = {s.tool_name for s in sels}
        assert "pricing_lookup_tool" in tool_names
        assert "technical_rag_tool" in tool_names


# ===================================================================
# request_builder tests
# ===================================================================

class TestBuildToolRequest:

    def test_builds_request_with_query_and_object(self) -> None:
        context = _make_context(query="CD3 antibody price")
        request = build_tool_request(context, "catalog_lookup_tool")
        assert request.tool_name == "catalog_lookup_tool"
        assert request.query == "CD3 antibody price"
        assert request.primary_object is not None
        assert request.primary_object.object_type == "product"

    def test_request_includes_constraints(self) -> None:
        context = _make_context(query="test")
        context.resolved_object_constraints = {"object_type": "product", "identifier": "TP-001"}
        context.demand_profile = DemandProfile(
            primary_demand="technical",
            group_demands=[
                GroupDemand(
                    intent="technical_question",
                    primary_demand="technical",
                    request_flags=["needs_protocol"],
                    object_type="product",
                    object_identifier="TP-001",
                    object_display_name="Test Product",
                )
            ],
        )
        context.active_demand = context.demand_profile.group_demands[0]
        request = build_tool_request(context, "tool_a", selected_tools=["tool_a", "tool_b"])
        constraints = request.constraints
        assert constraints.common["resolved_object_constraints"]["object_type"] == "product"
        assert "tool_a" in constraints.debug["selected_tools"]
        assert constraints.retrieval["demand"]["primary_demand"] == "technical"
        assert constraints.debug["semantic_demand"]["profile_primary_demand"] == "technical"

    def test_no_object_builds_empty_scope(self) -> None:
        context = _make_context(object_type="")
        request = build_tool_request(context, "general_tool")
        assert request.primary_object is None
        scope = request.constraints.scope
        assert scope["primary_object"] == {}

    def test_parser_constraints_populate_tool_dict(self) -> None:
        constraints = ParserConstraints(
            budget="5000 USD",
            format_or_size="50 kDa",
            destination="South Korea",
        )
        context = _make_context(parser_constraints=constraints)
        request = build_tool_request(context, "catalog_lookup_tool")
        tool = request.constraints.tool
        assert tool["budget"] == "5000 USD"
        assert tool["format_or_size"] == "50 kDa"
        assert tool["destination"] == "South Korea"
        # None fields should not appear
        assert "timeline_requirement" not in tool

    def test_parser_open_slots_populate_tool_dict(self) -> None:
        open_slots = ParserOpenSlots(
            experiment_type="Western Blot",
            pain_point="low yield",
        )
        context = _make_context(parser_open_slots=open_slots)
        request = build_tool_request(context, "rag_tool")
        tool = request.constraints.tool
        assert tool["experiment_type"] == "Western Blot"
        assert tool["pain_point"] == "low yield"
        # None fields should not appear
        assert "customer_goal" not in tool

    def test_tool_dict_empty_when_no_constraints(self) -> None:
        context = _make_context()
        request = build_tool_request(context, "some_tool")
        assert request.constraints.tool == {}


# ===================================================================
# engine tests
# ===================================================================

class TestBuildExecutionContext:

    def test_maps_ingestion_bundle_to_context(self) -> None:
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.ingestion import build_demand_profile
        from src.objects.models import ResolvedObjectState
        from src.common.models import IntentGroup

        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="CD3 antibody", normalized_query="CD3 antibody"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(),
                    request_flags=ParserRequestFlags(needs_price=True),
                    retrieval_hints=ParserRetrievalHints(),
                ),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        primary = ObjectCandidate(
            object_type="product",
            canonical_value="CD3",
            display_name="CD3 Antibody",
        )
        resolved = ResolvedObjectState(primary_object=primary)
        route = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        focus_group = IntentGroup(
            intent="pricing_question",
            request_flags=["needs_price"],
            object_type="product",
            object_identifier="",
            object_display_name="CD3 Antibody",
        )
        demand_profile = build_demand_profile(
            bundle.turn_signals.parser_signals,
            [focus_group],
        )

        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        ctx = build_execution_context(
            ingestion_bundle=bundle,
            resolved_object_state=resolved,
            route_decision=route,
            demand_profile=demand_profile,
            focus_group=focus_group,
            active_demand=scoped_demand,
        )

        assert ctx.query == "CD3 antibody"
        assert ctx.primary_object is not None
        assert ctx.primary_object.object_type == "product"
        assert ctx.dialogue_act.act == "inquiry"
        assert ctx.request_flags is not None
        assert ctx.request_flags.needs_price is True
        assert ctx.demand_profile is not None
        assert ctx.active_demand is not None
        assert ctx.active_demand.primary_demand == "commercial"

    def test_passes_parser_constraints_to_context(self) -> None:
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.objects.models import ResolvedObjectState

        constraints = ParserConstraints(format_or_size="50 kDa", budget="3000 USD")
        open_slots = ParserOpenSlots(experiment_type="ELISA")

        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="test", normalized_query="test"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(),
                    constraints=constraints,
                    open_slots=open_slots,
                ),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState()
        route = RouteDecision(action="execute", dialogue_act=DialogueActResult(act="inquiry"))

        ctx = build_execution_context(
            ingestion_bundle=bundle,
            resolved_object_state=resolved,
            route_decision=route,
        )

        assert ctx.parser_constraints is not None
        assert ctx.parser_constraints.format_or_size == "50 kDa"
        assert ctx.parser_constraints.budget == "3000 USD"
        assert ctx.parser_open_slots is not None
        assert ctx.parser_open_slots.experiment_type == "ELISA"


class TestResolveFollowUpIntent:
    """Backlog #8: follow_up turn substitutes prior_semantic_intent so RAG
    sees the meaningful retrieval bucket instead of the placeholder."""

    def _snapshot_with_prior(self, prior: str):
        from src.memory.models import IntentMemory, MemorySnapshot
        return MemorySnapshot(intent_memory=IntentMemory(prior_semantic_intent=prior))

    def test_substitutes_when_follow_up_with_meaningful_prior(self) -> None:
        snap = self._snapshot_with_prior("pricing_question")
        assert _resolve_follow_up_intent("follow_up", snap) == "pricing_question"

    def test_passes_through_non_follow_up(self) -> None:
        snap = self._snapshot_with_prior("pricing_question")
        assert _resolve_follow_up_intent("technical_question", snap) == "technical_question"

    def test_keeps_follow_up_when_prior_is_unknown(self) -> None:
        snap = self._snapshot_with_prior("unknown")
        assert _resolve_follow_up_intent("follow_up", snap) == "follow_up"

    def test_keeps_follow_up_when_prior_is_also_follow_up(self) -> None:
        # Belt-and-suspenders: writer-side fix should prevent this state, but
        # the resolver shouldn't loop to itself even if it ever sees one.
        snap = self._snapshot_with_prior("follow_up")
        assert _resolve_follow_up_intent("follow_up", snap) == "follow_up"

    def test_passes_through_when_no_memory(self) -> None:
        assert _resolve_follow_up_intent("follow_up", None) == "follow_up"


class TestAmbiguousBusinessLineAggregation:
    """杠杆三: when primary is unresolved, aggregate business_line from ambiguous_sets."""

    def _build_context_with_ambiguous(
        self,
        ambiguous_sets: list,
        primary: ObjectCandidate | None = None,
    ):
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.objects.models import ResolvedObjectState

        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="antibody discovery"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(context=ParserContext()),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState(
            primary_object=primary,
            ambiguous_sets=ambiguous_sets,
        )
        route = RouteDecision(action="execute", dialogue_act=DialogueActResult(act="inquiry"))

        return build_execution_context(
            ingestion_bundle=bundle,
            resolved_object_state=resolved,
            route_decision=route,
        )

    def test_aggregates_single_business_line_from_ambiguous_candidates(self) -> None:
        from src.objects.models import AmbiguousObjectSet

        candidates = [
            ObjectCandidate(
                object_type="service",
                canonical_value="Mouse Monoclonal Antibody",
                display_name="Mouse Monoclonal Antibody",
                business_line="antibody",
                is_ambiguous=True,
            ),
            ObjectCandidate(
                object_type="service",
                canonical_value="Rabbit Polyclonal Antibody Production",
                display_name="Rabbit Polyclonal Antibody Production",
                business_line="antibody",
                is_ambiguous=True,
            ),
        ]
        ambiguous_set = AmbiguousObjectSet(
            object_type="service",
            query_value="antibody discovery",
            candidates=candidates,
            resolution_strategy="clarify",
        )
        ctx = self._build_context_with_ambiguous([ambiguous_set])
        assert ctx.resolved_object_constraints.get("business_line") == "antibody"

    def test_does_not_aggregate_when_candidates_span_multiple_lines(self) -> None:
        from src.objects.models import AmbiguousObjectSet

        candidates = [
            ObjectCandidate(
                object_type="service",
                canonical_value="CAR-T Cell Design and Development",
                business_line="car_t_car_nk",
                is_ambiguous=True,
            ),
            ObjectCandidate(
                object_type="service",
                canonical_value="Mouse Monoclonal Antibody",
                business_line="antibody",
                is_ambiguous=True,
            ),
        ]
        ambiguous_set = AmbiguousObjectSet(
            object_type="service",
            candidates=candidates,
            resolution_strategy="clarify",
        )
        ctx = self._build_context_with_ambiguous([ambiguous_set])
        assert "business_line" not in ctx.resolved_object_constraints

    def test_does_not_override_existing_primary_business_line(self) -> None:
        from src.objects.models import AmbiguousObjectSet

        primary = ObjectCandidate(
            object_type="service",
            canonical_value="CAR-T Cell Design and Development",
            display_name="CAR-T Development",
            business_line="car_t_car_nk",
        )
        ambiguous_set = AmbiguousObjectSet(
            object_type="service",
            candidates=[
                ObjectCandidate(
                    object_type="service",
                    canonical_value="Mouse Monoclonal Antibody",
                    business_line="antibody",
                    is_ambiguous=True,
                ),
            ],
            resolution_strategy="clarify",
        )
        ctx = self._build_context_with_ambiguous([ambiguous_set], primary=primary)
        assert ctx.resolved_object_constraints.get("business_line") == "car_t_car_nk"


class TestRunExecutor:

    def setup_method(self) -> None:
        clear_registry()

    def teardown_method(self) -> None:
        clear_registry()

    def test_returns_empty_when_no_tools_match(self) -> None:
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.objects.models import ResolvedObjectState

        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="hello"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(context=ParserContext()),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState()
        route = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )

        result = run_executor(bundle, resolved, route)
        assert result.final_status == "empty"
        assert result.executed_calls == []

    def test_dispatches_and_merges_tool_results(self) -> None:
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.objects.models import ResolvedObjectState

        def fake_executor(request: ToolRequest) -> ToolResult:
            return ToolResult(
                tool_name=request.tool_name,
                status="ok",
                primary_records=[{"display_name": "CD3 Antibody", "catalog_no": "A100"}],
                structured_facts={"species": ["human"]},
            )

        register_tool(
            tool_name="catalog_lookup_tool",
            executor=fake_executor,
            capability=ToolCapability(
                tool_name="catalog_lookup_tool",
                supported_object_types=["product"],
                supported_demands=["commercial"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["structured_lookup"],
            ),
        )

        primary = ObjectCandidate(
            object_type="product",
            canonical_value="CD3",
            display_name="CD3 Antibody",
            identifier="A100",
            identifier_type="catalog_no",
        )
        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="CD3 antibody", normalized_query="CD3 antibody"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(context=ParserContext()),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState(primary_object=primary)
        route = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )

        result = run_executor(bundle, resolved, route)

        assert result.final_status == "ok"
        assert len(result.executed_calls) == 1
        assert result.executed_calls[0].tool_name == "catalog_lookup_tool"
        assert result.executed_calls[0].status == "ok"
        assert "catalog_lookup_tool" in result.merged_results.primary_facts

    def test_retries_with_fallback_when_primary_returns_empty(self) -> None:
        """When primary (commercial) returns empty, demand-aware fallback retries with RAG."""
        from src.ingestion.models import (
            IngestionBundle, TurnCore, TurnSignals,
            ParserSignals, ParserContext, DeterministicSignals,
            ReferenceSignals,
        )
        from src.objects.models import ResolvedObjectState

        def empty_catalog(request: ToolRequest) -> ToolResult:
            return ToolResult(tool_name=request.tool_name, status="empty")

        def ok_rag(request: ToolRequest) -> ToolResult:
            return ToolResult(
                tool_name=request.tool_name,
                status="ok",
                unstructured_snippets=[{"content": "CAR-T workflow info"}],
            )

        register_tool(
            tool_name="catalog_lookup_tool",
            executor=empty_catalog,
            capability=ToolCapability(
                tool_name="catalog_lookup_tool",
                supported_object_types=["product"],
                supported_demands=["commercial"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["structured_lookup"],
                supported_request_flags=["needs_availability"],
            ),
        )
        register_tool(
            tool_name="technical_rag_tool",
            executor=ok_rag,
            capability=ToolCapability(
                tool_name="technical_rag_tool",
                supported_object_types=["product", "service"],
                supported_demands=["technical"],
                supported_dialogue_acts=["inquiry"],
                supported_modalities=["unstructured_retrieval"],
                supported_request_flags=["needs_protocol"],
            ),
        )

        primary = ObjectCandidate(
            object_type="product",
            canonical_value="CAR-T",
            display_name="CAR-T",
        )
        bundle = IngestionBundle(
            turn_core=TurnCore(raw_query="CAR-T availability and protocol", normalized_query="CAR-T availability and protocol"),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(semantic_intent="product_inquiry"),
                    request_flags=ParserRequestFlags(needs_availability=True, needs_protocol=True),
                ),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState(primary_object=primary)
        route = RouteDecision(action="execute", dialogue_act=DialogueActResult(act="inquiry"))
        focus_group = IntentGroup(
            intent="product_inquiry",
            request_flags=["needs_availability", "needs_protocol"],
            object_type="product",
            object_display_name="CAR-T",
            confidence=0.85,
        )
        demand_profile = DemandProfile(
            primary_demand="commercial",
            secondary_demands=["technical"],
            active_request_flags=["needs_availability", "needs_protocol"],
            group_demands=[GroupDemand(
                intent="product_inquiry",
                primary_demand="commercial",
                secondary_demands=["technical"],
                request_flags=["needs_availability", "needs_protocol"],
                demand_confidence=0.9,
            )],
        )

        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        result = run_executor(
            bundle, resolved, route,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        tool_names = [call.tool_name for call in result.executed_calls]
        assert "catalog_lookup_tool" in tool_names
        assert "technical_rag_tool" in tool_names
        assert result.final_status == "ok"


# ===================================================================
# completeness tests
# ===================================================================

class TestEvaluateCompleteness:

    def setup_method(self) -> None:
        clear_registry()
        # Register tools so demand-aware fallback can find them
        register_tool(
            tool_name="catalog_lookup_tool",
            executor=lambda r: _make_tool_result(r.tool_name),
            capability=ToolCapability(tool_name="catalog_lookup_tool",
                supported_object_types=["product", "service"],
                supported_demands=["commercial"],
                supported_modalities=["structured_lookup"],
                supported_request_flags=["needs_availability"]),
        )
        register_tool(
            tool_name="technical_rag_tool",
            executor=lambda r: _make_tool_result(r.tool_name),
            capability=ToolCapability(tool_name="technical_rag_tool",
                supported_object_types=["product", "service"],
                supported_demands=["technical"],
                supported_modalities=["unstructured_retrieval"],
                supported_request_flags=["needs_protocol", "needs_troubleshooting",
                    "needs_recommendation", "needs_regulatory_info"]),
        )
        register_tool(
            tool_name="shipping_lookup_tool",
            executor=lambda r: _make_tool_result(r.tool_name),
            capability=ToolCapability(tool_name="shipping_lookup_tool",
                supported_object_types=["shipment", "order"],
                supported_demands=["operational"],
                supported_modalities=["external_api"],
                supported_request_flags=["needs_shipping_info"]),
        )

    def teardown_method(self) -> None:
        clear_registry()

    def test_sufficient_when_primary_ok_with_data(self) -> None:
        context = _make_context()
        calls = [_make_executed_call(
            "catalog_lookup_tool", "ok",
            result=_make_tool_result("catalog_lookup_tool", "ok", primary_records=[{"name": "CD3"}]),
        )]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "sufficient"

    def test_retry_fallback_when_all_empty_with_demand(self) -> None:
        """All empty + technical demand → demand-aware fallback finds RAG."""
        context = _make_context(object_type="product")
        context.active_demand = GroupDemand(
            primary_demand="technical", request_flags=["needs_protocol"],
        )
        calls = [_make_executed_call("catalog_lookup_tool", "empty")]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "retry_with_fallback"
        assert result.suggest_tool == "technical_rag_tool"

    def test_done_empty_when_all_tools_exhausted(self) -> None:
        context = _make_context()
        calls = [
            _make_executed_call("catalog_lookup_tool", "empty"),
            _make_executed_call("technical_rag_tool", "empty"),
        ]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "done_empty"

    def test_done_error_when_all_error(self) -> None:
        context = _make_context()
        calls = [_make_executed_call("catalog_lookup_tool", "error")]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "done_error"

    def test_done_at_max_iterations(self) -> None:
        context = _make_context()
        calls = [_make_executed_call("catalog_lookup_tool", "empty")]
        result = evaluate_completeness(context, calls, 2, 3)
        assert result.verdict == "done_empty"

    def test_retry_when_flag_demand_unsatisfied(self) -> None:
        """needs_protocol active but only catalog called → demand unsatisfied → retry with RAG."""
        context = _make_context(semantic_intent="technical_question")
        context.active_demand = GroupDemand(
            primary_demand="technical", request_flags=["needs_protocol"],
        )
        calls = [_make_executed_call(
            "catalog_lookup_tool", "ok",
            result=_make_tool_result("catalog_lookup_tool", "ok", primary_records=[{"name": "CD3"}]),
        )]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "retry_add_tool"
        assert result.suggest_tool == "technical_rag_tool"

    def test_sufficient_when_demand_tool_already_called(self) -> None:
        """needs_protocol active + RAG already called → demand satisfied."""
        context = _make_context(semantic_intent="technical_question")
        context.active_demand = GroupDemand(
            primary_demand="technical", request_flags=["needs_protocol"],
        )
        calls = [
            _make_executed_call("technical_rag_tool", "ok",
                result=_make_tool_result("technical_rag_tool", "ok", unstructured_snippets=[{"content": "info"}])),
        ]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "sufficient"

    def test_retry_add_shipping_when_demanded(self) -> None:
        """needs_shipping_info active but shipping tool not called → retry."""
        context = _make_context(semantic_intent="shipping_question")
        context.active_demand = GroupDemand(
            primary_demand="operational", request_flags=["needs_shipping_info"],
        )
        calls = [_make_executed_call(
            "order_lookup_tool", "ok",
            result=_make_tool_result("order_lookup_tool", "ok", primary_records=[{"order": "123"}]),
        )]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "retry_add_tool"
        assert result.suggest_tool == "shipping_lookup_tool"

    def test_no_retry_when_no_active_demand_and_primary_ok(self) -> None:
        """No active_demand + primary ok → sufficient (no phantom demand)."""
        context = _make_context(semantic_intent="product_inquiry")
        calls = [_make_executed_call(
            "catalog_lookup_tool", "ok",
            result=_make_tool_result("catalog_lookup_tool", "ok", primary_records=[{"name": "CD3"}]),
        )]
        result = evaluate_completeness(context, calls, 0, 3)
        assert result.verdict == "sufficient"
