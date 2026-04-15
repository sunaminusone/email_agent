"""E2E integration tests for technical inquiry (技术咨询) flow.

Verifies that a technical question travels correctly through the full
pipeline: ingestion → demand → routing → execution → response.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.models import DemandProfile, GroupDemand, IntentGroup
from src.ingestion.demand_profile import narrow_demand_profile
from src.common.execution_models import ExecutedToolCall, ExecutionResult
from src.executor.engine import run_executor
from src.ingestion import build_demand_profile
from src.routing.intent_assembly import assemble_intent_groups
from src.ingestion.models import (
    IngestionBundle,
    ParserContext,
    ParserRequestFlags,
    ParserSignals,
    TurnCore,
    TurnSignals,
    DeterministicSignals,
    ReferenceSignals,
)
from src.objects.models import ObjectCandidate, ResolvedObjectState
from src.responser import ResponseInput, build_response_bundle
from src.routing.models import DialogueActResult, RouteDecision
from src.routing.orchestrator import route
from src.tools.models import ToolCapability, ToolRequest, ToolResult
from src.tools.registry import register_tool, clear_registry


# ---------------------------------------------------------------------------
# Fake tool executors
# ---------------------------------------------------------------------------

def _fake_rag_executor(request: ToolRequest) -> ToolResult:
    return ToolResult(
        tool_name=request.tool_name,
        status="ok",
        unstructured_snippets=[{
            "content": "The CAR-T cell therapy development workflow involves: "
                       "1) Target selection, 2) Antibody screening, "
                       "3) Construct design, 4) Viral vector production, "
                       "5) T-cell transduction and expansion.",
            "title": "CAR-T Development Protocol",
            "section_type": "protocol_overview",
        }],
    )


def _fake_catalog_executor(request: ToolRequest) -> ToolResult:
    return ToolResult(
        tool_name=request.tool_name,
        status="ok",
        primary_records=[{
            "display_name": "Anti-CD3 Antibody",
            "catalog_no": "AB-100",
            "species": "human",
        }],
        structured_facts={"species": ["human"], "application": ["flow cytometry"]},
    )


# ---------------------------------------------------------------------------
# Shared setup/teardown
# ---------------------------------------------------------------------------

def _register_standard_tools():
    """Register a minimal realistic tool set: RAG + catalog."""
    register_tool(
        tool_name="technical_rag_tool",
        executor=_fake_rag_executor,
        capability=ToolCapability(
            tool_name="technical_rag_tool",
            supported_object_types=["product", "service"],
            supported_demands=["technical"],
            supported_dialogue_acts=["inquiry"],
            supported_modalities=["unstructured_retrieval"],
            supported_request_flags=[
                "needs_protocol", "needs_troubleshooting",
                "needs_recommendation", "needs_regulatory_info",
                "needs_documentation",
            ],
        ),
    )
    register_tool(
        tool_name="catalog_lookup_tool",
        executor=_fake_catalog_executor,
        capability=ToolCapability(
            tool_name="catalog_lookup_tool",
            supported_object_types=["product", "service"],
            supported_demands=["commercial"],
            supported_dialogue_acts=["inquiry"],
            supported_modalities=["structured_lookup"],
            supported_request_flags=["needs_availability", "needs_price"],
        ),
    )


# ===================================================================
# G1: Pure technical inquiry WITHOUT object
# ===================================================================

class TestTechnicalInquiryNoObject:
    """Technical question with no resolved object — full pipeline."""

    def setup_method(self):
        clear_registry()
        _register_standard_tools()

    def teardown_method(self):
        clear_registry()

    def _build_scenario(self):
        """Build all pipeline inputs for a pure technical question."""
        ingestion_bundle = IngestionBundle(
            turn_core=TurnCore(
                raw_query="What is the CAR-T cell therapy development workflow?",
                normalized_query="What is the CAR-T cell therapy development workflow?",
            ),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(primary_intent="technical_question"),
                    request_flags=ParserRequestFlags(needs_protocol=True),
                ),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        resolved = ResolvedObjectState(
            resolution_reason="No object found.",
        )
        intent_groups = assemble_intent_groups(
            request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
            resolved_objects=[None],
            primary_intent="technical_question",
        )
        demand_profile = build_demand_profile(
            ingestion_bundle.turn_signals.parser_signals,
            intent_groups,
        )
        return ingestion_bundle, resolved, intent_groups, demand_profile

    def test_demand_classified_as_technical(self):
        """Demand profile primary should be 'technical' with flag-based confidence."""
        _, _, _, demand_profile = self._build_scenario()

        assert demand_profile.primary_demand == "technical"
        assert "needs_protocol" in demand_profile.active_request_flags
        assert demand_profile.group_demands[0].demand_confidence == 0.9

    def test_routes_to_execute_without_object(self):
        """Technical demand allows execution even without a resolved object."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        decision = route(
            ingestion_bundle, resolved,
            focus_group=focus_group, scoped_demand=scoped_demand,
        )

        assert decision.action == "execute"
        assert decision.dialogue_act.act == "inquiry"

    def test_executor_selects_rag_not_catalog(self):
        """Tool selector should pick RAG for technical demand, not catalog."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )

        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        tool_names = [call.tool_name for call in result.executed_calls]
        assert "technical_rag_tool" in tool_names
        assert "catalog_lookup_tool" not in tool_names
        assert result.final_status == "ok"

    def test_response_mode_is_direct_answer(self):
        """Pure technical → direct_answer with LLM rewrite."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        execution_result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        bundle = build_response_bundle(ResponseInput(
            query="What is the CAR-T cell therapy development workflow?",
            locale="en",
            execution_result=execution_result,
            dialogue_act=DialogueActResult(act="inquiry"),
            demand_profile=demand_profile,
        ))

        assert bundle.response_plan.response_mode == "direct_answer"
        assert bundle.response_plan.should_use_llm_rewrite is True
        assert bundle.composed_response.response_type == "answer"

    def test_response_contains_rag_content(self):
        """Response message should include content from the RAG tool."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        execution_result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        bundle = build_response_bundle(ResponseInput(
            query="What is the CAR-T cell therapy development workflow?",
            locale="en",
            execution_result=execution_result,
            dialogue_act=DialogueActResult(act="inquiry"),
            demand_profile=demand_profile,
        ))

        msg = bundle.composed_response.message
        assert any(term in msg for term in ["CAR-T", "Target selection", "T-cell"])

    def test_memory_update_stores_technical_demand(self):
        """Memory should record last_demand_type=technical for continuity."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        execution_result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        bundle = build_response_bundle(ResponseInput(
            query="What is the CAR-T cell therapy development workflow?",
            locale="en",
            execution_result=execution_result,
            dialogue_act=DialogueActResult(act="inquiry"),
            demand_profile=demand_profile,
        ))

        mem = bundle.response_plan.memory_update.response_memory
        assert mem.last_demand_type == "technical"
        assert "needs_protocol" in mem.last_demand_flags


# ===================================================================
# G2: Technical inquiry WITH resolved object
# ===================================================================

class TestTechnicalInquiryWithObject:
    """Technical question about a known product — demand should stay
    technical (not commercial), and RAG should be selected (not catalog)."""

    def setup_method(self):
        clear_registry()
        _register_standard_tools()

    def teardown_method(self):
        clear_registry()

    def _build_scenario(self):
        """Build pipeline inputs for a technical question about a product."""
        ingestion_bundle = IngestionBundle(
            turn_core=TurnCore(
                raw_query="What is the protocol for this CD3 antibody?",
                normalized_query="What is the protocol for this CD3 antibody?",
            ),
            turn_signals=TurnSignals(
                parser_signals=ParserSignals(
                    context=ParserContext(primary_intent="technical_question"),
                    request_flags=ParserRequestFlags(needs_protocol=True),
                ),
                deterministic_signals=DeterministicSignals(),
                reference_signals=ReferenceSignals(),
            ),
        )
        primary_object = ObjectCandidate(
            object_type="product",
            canonical_value="Anti-CD3 Antibody",
            display_name="Anti-CD3 Antibody",
            identifier="AB-100",
            identifier_type="catalog_number",
            confidence=0.95,
        )
        resolved = ResolvedObjectState(
            primary_object=primary_object,
            resolution_reason="Selected the strongest current-turn object candidate.",
        )
        intent_groups = assemble_intent_groups(
            request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
            resolved_objects=[primary_object],
            primary_intent="technical_question",
        )
        demand_profile = build_demand_profile(
            ingestion_bundle.turn_signals.parser_signals,
            intent_groups,
        )
        return ingestion_bundle, resolved, intent_groups, demand_profile

    def test_demand_is_technical_not_commercial(self):
        """Object type=product should NOT override demand to commercial."""
        _, _, _, demand_profile = self._build_scenario()

        assert demand_profile.primary_demand == "technical"
        assert "needs_protocol" in demand_profile.active_request_flags

    def test_routes_to_execute(self):
        """Technical + object → execute (has object, so always routes)."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        decision = route(
            ingestion_bundle, resolved,
            focus_group=focus_group, scoped_demand=scoped_demand,
        )

        assert decision.action == "execute"

    def test_executor_selects_rag_despite_product_object(self):
        """Even with a product object, RAG should be primary for technical demand.

        This is the critical assertion: object_type=product must NOT drag
        tool selection to catalog. The demand (technical) takes precedence.
        """
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        tool_names = [call.tool_name for call in result.executed_calls]
        assert "technical_rag_tool" in tool_names
        # Catalog should NOT be selected for pure technical demand
        assert "catalog_lookup_tool" not in tool_names
        assert result.final_status == "ok"

    def test_executor_passes_object_context_to_rag(self):
        """RAG tool request should carry the resolved object for scoping."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        rag_call = next(c for c in result.executed_calls if c.tool_name == "technical_rag_tool")
        assert rag_call.request.primary_object is not None
        assert rag_call.request.primary_object.object_type == "product"
        assert rag_call.request.primary_object.display_name == "Anti-CD3 Antibody"

    def test_response_is_direct_answer_with_content(self):
        """Full pipeline: technical + object → direct_answer with RAG content."""
        ingestion_bundle, resolved, intent_groups, demand_profile = self._build_scenario()
        focus_group = intent_groups[0]

        route_decision = RouteDecision(
            action="execute",
            dialogue_act=DialogueActResult(act="inquiry"),
        )
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)

        execution_result = run_executor(
            ingestion_bundle, resolved, route_decision,
            focus_group=focus_group,
            demand_profile=demand_profile,
            active_demand=scoped_demand,
        )

        bundle = build_response_bundle(ResponseInput(
            query="What is the protocol for this CD3 antibody?",
            locale="en",
            execution_result=execution_result,
            resolved_object_state=resolved,
            dialogue_act=DialogueActResult(act="inquiry"),
            demand_profile=demand_profile,
        ))

        assert bundle.response_plan.response_mode == "direct_answer"
        assert bundle.composed_response.response_type == "answer"
        assert bundle.composed_response.message  # non-empty
