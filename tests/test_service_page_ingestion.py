from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.retriever import retrieve_chunks
from src.rag.service import retrieve_technical_knowledge
from src.rag.service_page_ingestion import load_service_page_documents, parse_service_page_file
from src.rag.vectorstore import get_vectorstore, rebuild_vectorstore


def test_parse_service_page_file_produces_prechunked_documents():
    path = Path(
        "/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/"
        "promab_custom_gamma_delta_t_cell_development_rag_ready_v4.txt"
    )
    docs = parse_service_page_file(path)

    assert docs
    assert all(doc.metadata.get("prechunked") is True for doc in docs)
    assert any(doc.metadata.get("section_type") == "pricing_overview" for doc in docs)
    assert any("Plan A and Plan B" in doc.page_content for doc in docs)


def test_load_service_page_documents_covers_all_service_page_files():
    docs = load_service_page_documents()
    paths = {doc.metadata.get("source_path") for doc in docs}

    assert len(paths) == 27
    assert any("promab_custom_car_t_cell_development_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_mrna_lnp_gene_delivery_rag_ready.txt" in path for path in paths)
    assert any("promab_mouse_monoclonal_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_rabbit_polyclonal_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_rabbit_monoclonal_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_antibody_production_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_human_monoclonal_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_hybridoma_sequencing_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_recombinant_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_affinity_tune_humanization_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_bispecific_antibodies_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_flow_cytometry_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_cytokine_response_assay_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_t_cell_specificity_assay_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_t_cell_activation_proliferation_assay_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_macrophage_polarization_assay_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_dc_migration_assay_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_stable_cell_line_development_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_mammalian_expression_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_e_coli_expression_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_baculovirus_expression_rag_ready_v1.txt" in path for path in paths)
    assert any("promab_peptide_synthesis_rag_ready_v1.txt" in path for path in paths)


def test_service_page_ingestion_builds_phase_and_workflow_subchunks():
    docs = load_service_page_documents()

    assert any(doc.metadata.get("section_type") == "service_phase" for doc in docs)
    assert any(doc.metadata.get("section_type") == "workflow_step" for doc in docs)
    assert any(doc.metadata.get("section_type") == "plan_summary" for doc in docs)
    assert any(doc.metadata.get("plan_name") == "Plan B" and doc.metadata.get("phase_name") == "Phase I" for doc in docs)


def test_timeline_query_prefers_service_plan_material():
    get_vectorstore()
    result = retrieve_chunks(
        query="What is the CAR-NK project timeline?",
        top_k=5,
        business_line_hint="car_t_car_nk",
    )

    top_section_types_full = [match["metadata"].get("section_type") for match in result["matches"][:5]]

    assert any(section_type in {"service_plan", "pricing_overview", "plan_summary"} for section_type in top_section_types_full)


def test_after_step_query_prefers_next_workflow_step():
    get_vectorstore()
    result = retrieve_chunks(
        query="What happens after Hybridoma Sequencing in the CAR-T workflow?",
        top_k=5,
        business_line_hint="car_t_car_nk",
    )

    top_step_names = [match["metadata"].get("step_name") for match in result["matches"][:3]]

    assert "Lentivirus Production" in top_step_names


def test_plan_comparison_query_prefers_plan_comparison_chunk():
    get_vectorstore()
    result = retrieve_chunks(
        query="What is the difference between Plan A and Plan B for Custom Gamma Delta T Cell Development?",
        top_k=5,
        business_line_hint="car_t_car_nk",
    )

    top_section_types = [match["metadata"].get("section_type") for match in result["matches"][:3]]

    assert "plan_comparison" in top_section_types


def test_active_service_name_can_scope_broad_follow_up_query():
    get_vectorstore()
    result = retrieve_chunks(
        query="What models do you support?",
        top_k=5,
        business_line_hint="mrna_lnp",
        active_service_name="mRNA-LNP Gene Delivery",
    )

    top_match = result["matches"][0]["metadata"]

    assert top_match.get("service_name") == "mRNA-LNP Gene Delivery"
    assert top_match.get("section_type") == "model_support"


def test_active_service_name_can_scope_broad_timeline_follow_up_query():
    get_vectorstore()
    result = retrieve_chunks(
        query="What is the project timeline?",
        top_k=5,
        business_line_hint="mrna_lnp",
        active_service_name="mRNA-LNP Gene Delivery",
    )

    top_match = result["matches"][0]["metadata"]

    assert top_match.get("service_name") == "mRNA-LNP Gene Delivery"
    assert top_match.get("section_type") == "timeline_overview"


def test_active_service_name_can_scope_broad_validation_follow_up_query():
    get_vectorstore()
    result = retrieve_chunks(
        query="How do you validate the platform?",
        top_k=5,
        business_line_hint="mrna_lnp",
        active_service_name="mRNA-LNP Gene Delivery",
    )

    top_matches = [match["metadata"] for match in result["matches"][:3]]

    assert any(match.get("service_name") == "mRNA-LNP Gene Delivery" for match in top_matches)
    assert any(match.get("section_type") == "validation_models" for match in top_matches)


def test_active_service_name_rewrites_broad_service_plan_follow_up_query():
    get_vectorstore()
    scope_context = {
        "query": "What is the service plan?",
        "original_query": "What is the service plan?",
        "effective_query": "What is the service plan?",
        "context": {"primary_intent": "follow_up"},
        "turn_resolution": {"turn_type": "follow_up"},
        "entities": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
        "product_lookup_keys": {"service_names": [], "product_names": [], "catalog_numbers": [], "targets": []},
        "active_service_name": "mRNA-LNP Gene Delivery",
        "session_payload": {
            "active_service_name": "mRNA-LNP Gene Delivery",
            "active_entity": {"entity_kind": "service"},
        },
        "routing_memory": {
            "should_stick_to_active_route": True,
            "session_payload": {"active_entity": {"entity_kind": "service"}},
        },
    }
    result = retrieve_technical_knowledge(
        query="What is the service plan?",
        top_k=5,
        business_line_hint="mrna_lnp",
        active_service_name="mRNA-LNP Gene Delivery",
        scope_context=scope_context,
    )

    assert result["retrieval_debug"]["rewritten_query"] == "What is the service plan for mRNA-LNP Gene Delivery?"
    top_section_types = [match["chunk_label"] for match in result["matches"][:3]]

    assert any("Discovery Services Plan" in label for label in top_section_types)


def test_mouse_monoclonal_antibody_pricing_tiers_are_structured_in_metadata():
    path = Path(
        "/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/antibody/"
        "promab_mouse_monoclonal_antibodies_rag_ready_v1.txt"
    )
    docs = parse_service_page_file(path)
    by_title = {doc.metadata.get("section_title"): doc.metadata for doc in docs}

    phase_i = by_title["Discovery Package - Phase I"]
    assert phase_i.get("pricing_tier") == "ten_mice_or_more"
    assert phase_i.get("unit") == "mouse"
    assert phase_i.get("unit_price_usd") == "50"
    assert phase_i.get("setup_fee_usd") == "300"

    ascites_11_50 = by_title["Ascites Production Pricing - 11 to 50 Mice"]
    assert ascites_11_50.get("pricing_tier") == "11_to_50_mice"
    assert ascites_11_50.get("unit") == "mouse"
    assert ascites_11_50.get("unit_price_usd") == "55"
    assert ascites_11_50.get("setup_fee_usd") == "300"

    production_1l = by_title["Antibody Production Yield in Bioreactors - 1 Liter of Supernatant"]
    assert production_1l.get("pricing_tier") == "one_liter_supernatant"
    assert production_1l.get("unit") == "clone"
    assert production_1l.get("price_usd") == "3200"

    purification_500 = by_title["Antibody Purification Pricing - 500 Milliliters"]
    assert purification_500.get("pricing_tier") == "five_hundred_milliliters_input"
    assert purification_500.get("unit") == "ml"
    assert purification_500.get("price_usd") == "800"

    cold_storage = by_title["Cold Storage Pricing - 3 Vials or More"]
    assert cold_storage.get("pricing_tier") == "three_vials_or_more"
    assert cold_storage.get("unit") == "vial/month"
    assert cold_storage.get("unit_price_usd") == "30"


def test_active_service_name_can_scope_specific_antibody_pricing_query():
    rebuild_vectorstore()
    result = retrieve_chunks(
        query="How much is 1 liter purification?",
        top_k=5,
        business_line_hint="antibody",
        active_service_name="Mouse Monoclonal Antibodies",
        service_names=["Mouse Monoclonal Antibodies"],
    )

    top_match = result["matches"][0]["metadata"]

    assert top_match.get("service_name") == "Mouse Monoclonal Antibodies"
    assert top_match.get("section_title") == "Antibody Purification Pricing - 1 Liter Purification from Supernatant"
