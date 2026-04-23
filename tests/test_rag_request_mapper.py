from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.objects.models import ObjectCandidate
from src.routing.models import DialogueActResult
from src.tools.models import ToolConstraints, ToolRequest
from src.tools.rag.technical_tool import execute_technical_rag_lookup
from src.tools.rag.request_mapper import build_rag_lookup_params
from src.rag.context_matching import compute_retrieval_context_matches
from src.rag.retriever import _build_variant_observability
from src.rag.service import build_retrieval_queries
from src.rag.retriever import _build_query_variants, _compute_soft_score


def test_build_rag_lookup_params_normalizes_parser_context_into_retrieval_context() -> None:
    request = ToolRequest(
        tool_name="technical_rag_tool",
        query="How should I validate it?",
        primary_object=ObjectCandidate(
            object_type="service",
            canonical_value="Antibody production",
            display_name="Antibody production",
            business_line="antibody",
        ),
        dialogue_act=DialogueActResult(act="inquiry"),
        constraints=ToolConstraints(
            retrieval={
                "hints": {
                    "keywords": ["low yield", "ELISA"],
                    "expanded_queries": ["antibody production validation workflow"],
                },
                "business_line": "antibody",
            },
            tool={
                "experiment_type": "ELISA",
                "usage_context": "validation assay",
                "pain_point": "low yield",
                "other_notes": ["needs reproducibility"],
            },
            scope={
                "active_service_name": "Antibody production",
            },
        ),
    )

    params = build_rag_lookup_params(request)

    assert "experiment_type" not in params
    assert "usage_context" not in params
    assert params["retrieval_context"] == {
        "usage_context": "validation assay",
        "experiment_type": "ELISA",
        "pain_point": "low yield",
        "other_notes": ["needs reproducibility"],
        "keywords": ["low yield", "ELISA"],
    }


def test_build_retrieval_queries_uses_retrieval_context_for_contextual_queries() -> None:
    plan = build_retrieval_queries(
        query="How should I validate it?",
        retrieval_context={
            "experiment_type": "ELISA",
            "usage_context": "validation assay",
            "pain_point": "low yield",
            "keywords": ["specificity"],
        },
        active_service_name="Antibody production",
        service_names=["Antibody production"],
        scope_context={
            "query": "How should I validate it?",
            "active_service_name": "Antibody production",
            "context": {"primary_intent": "technical_question"},
            "entities": {
                "service_names": [],
                "product_names": [],
                "catalog_numbers": [],
                "targets": [],
            },
            "product_lookup_keys": {
                "service_names": [],
                "product_names": [],
                "catalog_numbers": [],
                "targets": [],
            },
            "routing_memory": {
                "should_stick_to_active_route": True,
            },
            "turn_resolution": {
                "turn_type": "follow_up",
            },
            "session_payload": {
                "active_entity": {
                    "entity_kind": "service",
                },
                "active_service_name": "Antibody production",
            },
        },
    )

    assert plan["rewritten_query"] == "How should I validate Antibody production?"
    assert plan["retrieval_context"]["experiment_type"] == "ELISA"
    contextual_query_texts = [item["query"] for item in plan["contextual_query_specs"]]
    assert any("ELISA" in item for item in contextual_query_texts)
    assert any("validation assay" in item for item in contextual_query_texts)
    assert any("specificity" in item for item in contextual_query_texts)


def test_execute_technical_rag_lookup_passes_retrieval_context_without_signature_break() -> None:
    request = ToolRequest(
        tool_name="technical_rag_tool",
        query="How should I validate it?",
        primary_object=ObjectCandidate(
            object_type="service",
            canonical_value="Antibody production",
            display_name="Antibody production",
            business_line="antibody",
        ),
        dialogue_act=DialogueActResult(act="inquiry"),
        constraints=ToolConstraints(
            retrieval={"hints": {"keywords": ["ELISA"]}},
            tool={
                "experiment_type": "ELISA",
                "usage_context": "validation assay",
            },
            scope={"active_service_name": "Antibody production"},
        ),
    )

    captured: dict[str, object] = {}

    def _fake_retrieve(**kwargs):
        captured.update(kwargs)
        return {
            "retrieval_mode": "test",
            "matches": [],
            "documents_found": 0,
            "confidence": {},
            "retrieval_debug": {},
            "query_variants": [],
        }

    with patch("src.rag.service.retrieve_technical_knowledge", side_effect=_fake_retrieve):
        result = execute_technical_rag_lookup(request)

    assert result.status == "empty"
    assert captured["query"] == "How should I validate it?"
    assert captured["retrieval_context"] == {
        "usage_context": "validation assay",
        "experiment_type": "ELISA",
        "keywords": ["ELISA"],
    }
    assert "experiment_type" not in captured
    assert "usage_context" not in captured


def test_query_variant_plan_preserves_context_diversity() -> None:
    variants = _build_query_variants(
        query="How should I validate it?",
        rewritten_query="How should I validate Antibody production?",
        contextual_query_specs=[
            {"query": "How should I validate it? ELISA", "kind": "context_experiment"},
            {"query": "How should I validate it? validation assay", "kind": "context_usage"},
            {"query": "How should I validate it? low yield", "kind": "context_pain_point"},
            {"query": "How should I validate it? specificity", "kind": "context_keyword"},
        ],
        active_service_name="Antibody production",
        service_names=["Antibody production", "Antibody production service"],
        expanded_queries=[
            "Antibody production validation workflow",
            "Antibody production service plan",
        ],
    )

    kinds = [item["kind"] for item in variants]
    queries = [item["query"] for item in variants]

    assert kinds[0] == "original"
    assert "rewrite_scope" in kinds
    assert "context_experiment" in kinds
    assert "context_usage" in kinds
    assert "context_keyword" in kinds or "context_pain_point" in kinds
    assert queries.count("Antibody production") <= 1


def test_compute_soft_score_boosts_retrieval_context_matches() -> None:
    scoped_match = {
        "rerank_score": 1.0,
        "content": "ELISA validation assay with low yield troubleshooting and specificity checks.",
        "metadata": {
            "section_type": "workflow_step",
            "service_name": "Antibody production",
            "section_title": "ELISA validation workflow",
            "chunk_label": "Specificity troubleshooting",
            "tags": "ELISA, validation assay, low yield, specificity",
        },
    }
    generic_match = {
        "rerank_score": 1.0,
        "content": "General workflow overview for antibody production services.",
        "metadata": {
            "section_type": "workflow_step",
            "service_name": "Antibody production",
            "section_title": "Workflow overview",
            "chunk_label": "General overview",
            "tags": "workflow",
        },
    }

    retrieval_context = {
        "experiment_type": "ELISA",
        "usage_context": "validation assay",
        "pain_point": "low yield",
        "keywords": ["specificity"],
    }

    scoped_score, scoped_breakdown = _compute_soft_score(
        scoped_match,
        intent_bucket="workflow",
        active_service_name="Antibody production",
        query="How should I validate it?",
        retrieval_context=retrieval_context,
        business_line_hint="antibody",
    )
    generic_score, generic_breakdown = _compute_soft_score(
        generic_match,
        intent_bucket="workflow",
        active_service_name="Antibody production",
        query="How should I validate it?",
        retrieval_context=retrieval_context,
        business_line_hint="antibody",
    )

    assert scoped_breakdown["experiment_type_boost"] > 0
    assert scoped_breakdown["usage_context_boost"] > 0
    assert scoped_breakdown["pain_point_boost"] > 0
    assert scoped_breakdown["keyword_boost"] > 0
    assert generic_breakdown["experiment_type_boost"] == 0
    assert generic_breakdown["usage_context_boost"] == 0
    assert scoped_score > generic_score


def test_compute_soft_score_business_line_boost_fires_on_match() -> None:
    from src.rag.retriever import _ACTIVE_BUSINESS_LINE_BOOST

    same_line_match = {
        "rerank_score": 1.0,
        "content": "Some chunk content.",
        "metadata": {
            "section_type": "workflow_step",
            "service_name": "Rabbit Polyclonal Antibody Production",
            "business_line": "antibody",
        },
    }
    other_line_match = {
        "rerank_score": 1.0,
        "content": "Some chunk content.",
        "metadata": {
            "section_type": "workflow_step",
            "service_name": "CAR-T Cell Design and Development",
            "business_line": "car_t_car_nk",
        },
    }

    same_score, same_breakdown = _compute_soft_score(
        same_line_match,
        intent_bucket="workflow",
        active_service_name="",
        query="antibody discovery overview",
        business_line_hint="antibody",
    )
    other_score, other_breakdown = _compute_soft_score(
        other_line_match,
        intent_bucket="workflow",
        active_service_name="",
        query="antibody discovery overview",
        business_line_hint="antibody",
    )

    assert same_breakdown["active_business_line_boost"] == _ACTIVE_BUSINESS_LINE_BOOST
    assert other_breakdown["active_business_line_boost"] == 0.0
    assert same_score > other_score


def test_compute_soft_score_business_line_boost_skips_unknown_hints() -> None:
    match = {
        "rerank_score": 1.0,
        "content": "",
        "metadata": {
            "section_type": "workflow_step",
            "business_line": "unknown",
        },
    }
    for hint in ("", "unknown", "cross_line"):
        _, breakdown = _compute_soft_score(
            match,
            intent_bucket="workflow",
            active_service_name="",
            query="q",
            business_line_hint=hint,
        )
        assert breakdown["active_business_line_boost"] == 0.0


def test_compute_soft_score_business_line_boost_stacks_additively_with_service_boost() -> None:
    from src.rag.retriever import _ACTIVE_ENTITY_BOOST, _ACTIVE_BUSINESS_LINE_BOOST

    match = {
        "rerank_score": 0.0,
        "content": "",
        "metadata": {
            "section_type": "workflow_step",
            "entity_type": "service",
            "entity_name": "CAR-T Cell Design and Development",
            "service_name": "CAR-T Cell Design and Development",
            "business_line": "car_t_car_nk",
        },
    }
    score, breakdown = _compute_soft_score(
        match,
        intent_bucket="workflow",
        active_service_name="CAR-T Cell Design and Development",
        query="how does CAR-T development work?",
        business_line_hint="car_t_car_nk",
    )

    assert breakdown["active_entity_boost"] == _ACTIVE_ENTITY_BOOST
    assert breakdown["active_business_line_boost"] == _ACTIVE_BUSINESS_LINE_BOOST
    # 2a: additive stacking — both boosts contribute.
    assert score >= _ACTIVE_ENTITY_BOOST + _ACTIVE_BUSINESS_LINE_BOOST


def test_context_matching_prefers_metadata_fields() -> None:
    match = {
        "content": "This section describes assay setup in detail.",
        "metadata": {
            "section_title": "Western Blot validation workflow",
            "chunk_label": "WB validation",
            "tags": "western blot, validation assay",
        },
    }

    matches = compute_retrieval_context_matches(
        match,
        {
            "experiment_type": "WB",
            "usage_context": "validation assay",
            "keywords": ["western blot", "validation assay"],
        },
    )

    assert matches["experiment_type"]["matched"] is True
    assert matches["experiment_type"]["source"] == "metadata"
    assert matches["usage_context"]["matched"] is True
    assert matches["usage_context"]["source"] == "metadata"
    assert matches["keywords"]["matched_count"] == 2
    assert all(item["source"] == "metadata" for item in matches["keywords"]["matches"])


def test_variant_observability_aggregates_kind_contributions() -> None:
    query_variant_plan = [
        {"query": "q1", "kind": "original"},
        {"query": "q2", "kind": "context_experiment"},
    ]
    raw_matches = [
        {
            "query_variant_kind": "original",
            "metadata": {"chunk_key": "a"},
        },
        {
            "query_variant_kind": "context_experiment",
            "metadata": {"chunk_key": "b"},
        },
        {
            "query_variant_kind": "context_experiment",
            "metadata": {"chunk_key": "a"},
        },
    ]
    deduped = [
        {
            "query_variant_kind": "original",
            "metadata": {"chunk_key": "a"},
        },
        {
            "query_variant_kind": "context_experiment",
            "metadata": {"chunk_key": "b"},
        },
    ]
    reranked_pool = list(deduped)
    final_matches = [deduped[1]]

    observability = _build_variant_observability(
        query_variant_plan=query_variant_plan,
        raw_matches=raw_matches,
        deduped=deduped,
        reranked_pool=reranked_pool,
        final_matches=final_matches,
    )

    original = observability["stats_by_kind"]["original"]
    context = observability["stats_by_kind"]["context_experiment"]

    assert original["raw_hits"] == 1
    assert original["unique_hits"] == 1
    assert original["exclusive_hits"] == 0
    assert context["raw_hits"] == 2
    assert context["unique_hits"] == 2
    assert context["hits_in_final_top_k"] == 1
    assert context["exclusive_hits"] == 1


def test_execute_technical_rag_lookup_exposes_variant_observability() -> None:
    request = ToolRequest(
        tool_name="technical_rag_tool",
        query="How should I validate it?",
        constraints=ToolConstraints(),
    )

    def _fake_retrieve(**kwargs):
        return {
            "retrieval_mode": "test",
            "matches": [],
            "documents_found": 0,
            "confidence": {},
            "query_variants": [],
            "retrieval_debug": {
                "variant_observability": {
                    "stats_by_kind": {
                        "context_experiment": {"hits_in_final_top_k": 1},
                    }
                }
            },
        }

    with patch("src.rag.service.retrieve_technical_knowledge", side_effect=_fake_retrieve):
        result = execute_technical_rag_lookup(request)

    assert result.structured_facts["variant_observability"]["stats_by_kind"]["context_experiment"]["hits_in_final_top_k"] == 1
