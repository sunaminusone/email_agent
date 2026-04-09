from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.retriever import retrieve_chunks
from src.rag.service import build_retrieval_queries, retrieve_technical_knowledge


def _active_service_scope_context(query: str = "What is the service plan?") -> dict:
    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "primary_intent": "follow_up",
        },
        "turn_resolution": {
            "turn_type": "follow_up",
        },
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
        "active_service_name": "mRNA-LNP Gene Delivery",
        "session_payload": {
            "active_service_name": "mRNA-LNP Gene Delivery",
            "active_entity": {
                "entity_kind": "service",
            },
        },
        "routing_memory": {
            "should_stick_to_active_route": True,
            "session_payload": {
                "active_entity": {
                    "entity_kind": "service",
                },
            },
        },
    }


def _active_product_scope_context(
    query: str = "What applications is this antibody validated for?",
) -> dict:
    return {
        "query": query,
        "original_query": query,
        "effective_query": query,
        "context": {
            "primary_intent": "technical_question",
        },
        "turn_resolution": {
            "turn_type": "follow_up",
        },
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
        "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
        "session_payload": {
            "active_product_name": "Mouse Monoclonal antibody to Nucleophosmin",
            "active_entity": {
                "entity_kind": "product",
                "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
            },
        },
        "routing_memory": {
            "should_stick_to_active_route": True,
            "session_payload": {
                "active_entity": {
                    "entity_kind": "product",
                    "display_name": "Mouse Monoclonal antibody to Nucleophosmin",
                },
            },
        },
    }


def test_build_retrieval_queries_rewrites_scoped_service_plan_follow_up():
    query_plan = build_retrieval_queries(
        query="What is the service plan?",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context(),
    )

    assert query_plan["rewritten_query"] == "What is the service plan for mRNA-LNP Gene Delivery?"
    assert query_plan["rewrite_reason"] == "injected_scope_for_service_plan"
    assert query_plan["intent_bucket"] == "service_plan"
    assert query_plan["effective_scope"]["scope_type"] == "service"
    assert query_plan["effective_scope"]["source"] == "active"
    assert "mRNA-LNP Gene Delivery discovery services plan" in query_plan["expanded_queries"]
    assert "mRNA-LNP Gene Delivery phases" in query_plan["expanded_queries"]


def test_build_retrieval_queries_adds_workflow_expansions_for_active_service_follow_up():
    query_plan = build_retrieval_queries(
        query="What happens next?",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context("What happens next?"),
    )

    assert query_plan["intent_bucket"] == "workflow"
    assert "mRNA-LNP Gene Delivery workflow" in query_plan["expanded_queries"]
    assert "mRNA-LNP Gene Delivery next step" in query_plan["expanded_queries"]


def test_build_retrieval_queries_adds_model_support_expansions_for_active_service_follow_up():
    query_plan = build_retrieval_queries(
        query="What models do you support?",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context("What models do you support?"),
    )

    assert query_plan["intent_bucket"] == "model_support"
    assert "mRNA-LNP Gene Delivery supported models" in query_plan["expanded_queries"]
    assert "mRNA-LNP Gene Delivery cell types" in query_plan["expanded_queries"]


def test_build_retrieval_queries_skips_rewrite_for_explicitly_scoped_query():
    query = "What is the service plan for mRNA-LNP Gene Delivery?"
    query_plan = build_retrieval_queries(
        query=query,
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context(query),
    )

    assert query_plan["rewritten_query"] == ""
    assert query_plan["rewrite_reason"] == "no_rewrite_query_already_scoped"


def test_retrieve_technical_knowledge_includes_rewrite_debug_and_variant(monkeypatch):
    captured: dict = {}

    def fake_retrieve_chunks(**kwargs):
        captured.update(kwargs)
        return {
            "retrieval_mode": "fake",
            "query_variants": [
                kwargs["query"],
                kwargs["rewritten_query"],
                *kwargs.get("expanded_queries", []),
            ],
            "matches": [
                {
                    "query_variant": kwargs["query"],
                    "score": 0.1,
                    "raw_score": 0.1,
                    "content": "Plan summary content",
                    "section_boost": 0.08,
                    "metadata": {
                        "section_type": "plan_summary",
                        "chunk_label": "Discovery Services Plan - Summary",
                        "file_name": "mock.txt",
                        "business_line": "mrna_lnp",
                    },
                }
            ],
        }

    monkeypatch.setattr("src.rag.service.retrieve_chunks", fake_retrieve_chunks)

    result = retrieve_technical_knowledge(
        query="What is the service plan?",
        business_line_hint="mrna_lnp",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context(),
    )

    assert captured["rewritten_query"] == "What is the service plan for mRNA-LNP Gene Delivery?"
    assert result["query_variants"][1] == "What is the service plan for mRNA-LNP Gene Delivery?"
    assert result["retrieval_debug"]["effective_scope_type"] == "service"
    assert result["retrieval_debug"]["effective_scope_name"] == "mRNA-LNP Gene Delivery"
    assert result["retrieval_debug"]["rewrite_reason"] == "injected_scope_for_service_plan"
    assert result["retrieval_debug"]["section_boost_applied"]["intent_bucket"] == "service_plan"
    assert result["retrieval_debug"]["section_boost_applied"]["boosted_match_count"] == 1
    assert result["retrieval_debug"]["section_boost_applied"]["boosted_sections"][0]["section_type"] == "plan_summary"


def test_build_retrieval_queries_does_not_inject_scope_when_none_is_available():
    query_plan = build_retrieval_queries(
        query="What about this one?",
        scope_context={
            "query": "What about this one?",
            "original_query": "What about this one?",
            "effective_query": "What about this one?",
            "context": {"primary_intent": "follow_up"},
            "turn_resolution": {"turn_type": "follow_up"},
            "entities": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
            "product_lookup_keys": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
            "session_payload": {"active_entity": {"entity_kind": ""}},
            "routing_memory": {"should_stick_to_active_route": False, "session_payload": {"active_entity": {"entity_kind": ""}}},
        },
    )

    assert query_plan["rewritten_query"] == ""
    assert query_plan["expanded_queries"] == []
    assert query_plan["effective_scope"]["scope_type"] == ""


def test_build_retrieval_queries_rewrites_context_dependent_product_follow_up():
    query_plan = build_retrieval_queries(
        query="What applications is this antibody validated for?",
        active_product_name="Mouse Monoclonal antibody to Nucleophosmin",
        scope_context=_active_product_scope_context(),
    )

    assert query_plan["effective_scope"]["scope_type"] == "product"
    assert query_plan["effective_scope"]["source"] == "active"
    assert (
        query_plan["rewritten_query"]
        == "What applications is Mouse Monoclonal antibody to Nucleophosmin validated for?"
    )
    assert query_plan["rewrite_reason"] == "injected_scope_for_referential_entity"
    assert query_plan["intent_bucket"] == "product_attributes"


def test_build_retrieval_queries_does_not_guess_product_scope_without_active_context():
    query_plan = build_retrieval_queries(
        query="What applications is this antibody validated for?",
        scope_context={
            "query": "What applications is this antibody validated for?",
            "original_query": "What applications is this antibody validated for?",
            "effective_query": "What applications is this antibody validated for?",
            "context": {"primary_intent": "technical_question"},
            "turn_resolution": {"turn_type": "follow_up"},
            "entities": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
            "product_lookup_keys": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
            "session_payload": {"active_entity": {"entity_kind": ""}},
            "routing_memory": {"should_stick_to_active_route": False, "session_payload": {"active_entity": {"entity_kind": ""}}},
        },
    )

    assert query_plan["rewritten_query"] == ""
    assert query_plan["effective_scope"]["scope_type"] == ""


def test_build_retrieval_queries_skips_keyword_expansion_for_contact_style_requests():
    query_plan = build_retrieval_queries(
        query="Connect me to support for this service",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=_active_service_scope_context("Connect me to support for this service"),
    )

    assert query_plan["effective_scope"]["scope_type"] == ""
    assert query_plan["rewrite_reason"].startswith("no_rewrite_")
    assert query_plan["expanded_queries"] == []


def test_section_type_boosting_prefers_plan_sections_for_service_plan_bucket(monkeypatch):
    documents = [
        (
            SimpleNamespace(
                page_content="FAQ content",
                metadata={"chunk_key": "faq", "section_type": "faq", "service_name": "mRNA-LNP Gene Delivery"},
            ),
            0.10,
        ),
        (
            SimpleNamespace(
                page_content="Plan summary content",
                metadata={"chunk_key": "plan", "section_type": "plan_summary", "service_name": "mRNA-LNP Gene Delivery"},
            ),
            0.20,
        ),
        (
            SimpleNamespace(
                page_content="Service phase content",
                metadata={"chunk_key": "phase", "section_type": "service_phase", "service_name": "mRNA-LNP Gene Delivery"},
            ),
            0.30,
        ),
    ]

    class FakeStore:
        def similarity_search_with_score(self, query, k=0):
            return documents

    def fake_rerank(query, matches, *, top_k):
        scores = {
            "faq": 0.90,
            "plan": 0.83,
            "phase": 0.82,
        }
        reranked = []
        for match in matches:
            reranked.append(
                {
                    **match,
                    "rerank_score": scores[match["metadata"]["chunk_key"]],
                }
            )
        reranked.sort(key=lambda item: (-item["rerank_score"], item["score"]))
        return reranked[:top_k]

    monkeypatch.setattr("src.rag.retriever.get_vectorstore", lambda: FakeStore())
    monkeypatch.setattr("src.rag.retriever.rerank_matches", fake_rerank)

    result = retrieve_chunks(
        query="What is the service plan?",
        intent_bucket="service_plan",
        active_service_name="mRNA-LNP Gene Delivery",
        top_k=3,
    )

    assert result["matches"][0]["metadata"]["section_type"] == "plan_summary"
    assert result["matches"][0]["section_boost"] == 0.08


def test_section_type_boosting_is_inactive_without_supported_bucket(monkeypatch):
    documents = [
        (
            SimpleNamespace(
                page_content="FAQ content",
                metadata={"chunk_key": "faq", "section_type": "faq", "service_name": "mRNA-LNP Gene Delivery"},
            ),
            0.10,
        ),
        (
            SimpleNamespace(
                page_content="Plan summary content",
                metadata={"chunk_key": "plan", "section_type": "plan_summary", "service_name": "mRNA-LNP Gene Delivery"},
            ),
            0.20,
        ),
    ]

    class FakeStore:
        def similarity_search_with_score(self, query, k=0):
            return documents

    def fake_rerank(query, matches, *, top_k):
        scores = {
            "faq": 0.90,
            "plan": 0.83,
        }
        reranked = []
        for match in matches:
            reranked.append(
                {
                    **match,
                    "rerank_score": scores[match["metadata"]["chunk_key"]],
                }
            )
        reranked.sort(key=lambda item: (-item["rerank_score"], item["score"]))
        return reranked[:top_k]

    monkeypatch.setattr("src.rag.retriever.get_vectorstore", lambda: FakeStore())
    monkeypatch.setattr("src.rag.retriever.rerank_matches", fake_rerank)

    result = retrieve_chunks(
        query="What is the service plan?",
        intent_bucket="general_technical",
        active_service_name="mRNA-LNP Gene Delivery",
        top_k=2,
    )

    assert result["matches"][0]["metadata"]["section_type"] == "faq"
    assert "section_boost" not in result["matches"][0]
