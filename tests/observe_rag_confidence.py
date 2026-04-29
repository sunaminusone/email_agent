"""Observation script: sweep a query corpus through the real RAG retriever
and tabulate the confidence signals.

This is NOT a pytest test (filename does not match `test_*.py`). Its purpose
is to collect the observed distribution of `top_final_score` / `top_margin`
across representative query categories, so that Phase-2 can pick informed
thresholds for RAG-confidence-driven handoff.

Usage:
    python tests/observe_rag_confidence.py
    python tests/observe_rag_confidence.py --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.objects.registries.service_registry import KNOWN_BUSINESS_LINES
from src.rag.service import retrieve_technical_knowledge


def _validate_corpus(corpus: list[tuple[str, str, dict[str, Any]]]) -> None:
    """Fail fast when a corpus row carries an unknown business_line_hint.

    Silent hint typos (e.g. "car_t" vs "car_t_car_nk") cause the Layer-1
    soft boost to produce 0 with no error — see the 2026-04-22 incident
    documented in project_rag_active_service_data_flow.md.
    """
    allowed = KNOWN_BUSINESS_LINES | {""}
    for _, query, ctx in corpus:
        hint = str(ctx.get("business_line_hint", "") or "").strip()
        if hint not in allowed:
            raise ValueError(
                f"business_line_hint={hint!r} is not in KNOWN_BUSINESS_LINES "
                f"for query {query!r}. Allowed: {sorted(KNOWN_BUSINESS_LINES)}"
            )


# Hypothesis labels ("high" / "medium" / "low" / "irrelevant") represent what
# we GUESS the confidence class should be — the whole point of this script is
# to check whether reality matches. Do not treat them as ground truth.
CORPUS: list[tuple[str, str, dict[str, Any]]] = [
    # --- I. High: explicit service + well-known technical intent ---
    ("high", "What is the service plan for CAR-T cell therapy?",
        {"business_line_hint": "car_t_car_nk"}),
    ("high", "What is the workflow for antibody production?",
        {"business_line_hint": "antibody"}),
    ("high", "What models do you support for mRNA LNP development?",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "How long does CAR-T cell therapy development take?",
        {"business_line_hint": "car_t_car_nk"}),
    ("high", "What are the phases in antibody discovery?",
        {"business_line_hint": "antibody"}),

    # --- II. Medium: pronouns / term pairs / needs rewriting ---
    ("medium", "How does it work?",
        {"active_service_name": "CAR-T cell therapy", "business_line_hint": "car_t_car_nk"}),
    ("medium", "I need antibody purification for 1 liter",
        {"active_service_name": "Antibody production", "business_line_hint": "antibody"}),
    ("medium", "Quote for antibody production service",
        {"business_line_hint": "antibody"}),
    ("medium", "What's the timeline for this service?",
        {"active_service_name": "CAR-T cell therapy", "business_line_hint": "car_t_car_nk"}),

    # --- III. Non-technical but still customer-service-ish (should score low) ---
    ("low", "What's your contact phone number?", {}),
    ("low", "Do you ship to Europe?", {}),
    ("low", "When will I receive the invoice?", {}),
    ("low", "Who is your sales rep for antibody products?",
        {"business_line_hint": "antibody"}),

    # --- IV. Irrelevant / off-domain (should score lowest) ---
    ("irrelevant", "What's the weather today in Boston?", {}),
    ("irrelevant", "Can you recommend a good restaurant?", {}),
    ("irrelevant", "Tell me about COVID vaccines", {}),

    # --- V. Signal-rich scenarios (for variant contribution analysis) ---
    # Each row here aims to activate multiple variant kinds so that
    # observe_rag_variant_contribution can measure per-kind contribution.
    # See project_rag_architecture_backlog.md item A.
    ("high", "How should I validate it for specificity?",
        {"active_service_name": "Antibody production",
         "business_line_hint": "antibody",
         "retrieval_context": {
             "experiment_type": "ELISA",
             "usage_context": "validation assay",
             "pain_point": "low yield",
             "keywords": ["specificity", "low yield"],
         }}),
    ("high", "We need FDA-compliant antibody production with full audit trail",
        {"active_service_name": "Antibody production",
         "business_line_hint": "antibody",
         "retrieval_context": {
             "regulatory_or_compliance_note": "FDA IND requirements",
             "keywords": ["audit trail", "batch documentation"],
         }}),
    ("high", "Which of these antibodies works best for flow cytometry?",
        {"business_line_hint": "antibody",
         "product_names": ["clone 12G3 anti-CD3", "polyclonal anti-CD3", "OKT3"],
         "retrieval_context": {"experiment_type": "flow cytometry"}}),
    ("high", "Tell me about the workflow",
        {"active_service_name": "Antibody production",
         "business_line_hint": "antibody",
         "retrieval_hints": {
             "expanded_queries": [
                 "hybridoma screening process",
                 "antibody purification steps",
             ]
         }}),
    ("medium", "What about the validation data?",
        {"active_service_name": "Antibody production",
         "business_line_hint": "antibody"}),
    ("medium", "Which cell lines does this platform use?",
        {"active_service_name": "CAR-T cell therapy",
         "business_line_hint": "car_t_car_nk"}),

    # --- VI. Real first-inquiry samples (HubSpot sample20, 2026-04-23) ---
    # Sourced from data/processed/production_conversation_first_inquiries_sample20.csv.
    # Cold-start scenarios (no active_service_name) — matches the reality that
    # first-inquiry form submissions arrive with no prior memory. Signatures,
    # sign-offs, and "[From Promab Web Form]" markers stripped; line breaks and
    # bullet lists folded to single-line prose. Category hypotheses derived from
    # form fields + message content, not from the reply text.
    ("high", "We are interested in sequencing the VH and VL of a murine hybridoma, "
        "and possibly in generating a scFv with the resulting sequence. Can you "
        "provide me with a quote for this?",
        {"business_line_hint": "antibody"}),
    ("high", "For research purposes only, we are interested in a 'split' CAR for "
        "transduction into T cells followed by cytotoxicity assessment on target "
        "cells - 2-4 constructs.",
        {"business_line_hint": "car_t_car_nk"}),
    # Form field says "Peptide Synthesis" but message intent is antibody (hybridoma mAb
    # development using peptide immunogens) — observes whether content signals win over
    # form-field drift.
    ("high", "I have two peptide sequences I would love for the company to develop "
        "monoclonal antibodies (Hybridoma technology). As deliverables we expect: "
        "up to 20 best clones (supernatant samples) at the polyclonal stage, "
        "1 hybridoma cell line, at least 2 mg of purified antibody, at least 2 mg "
        "of peptide antigen, and project report. How much would this cost and how "
        "long will it take?",
        {"business_line_hint": "antibody"}),
    ("high", "I am an investigator interested in making a Dendritic Cell BCMA "
        "vaccine using mRNA for Multiple Myeloma patients. I'd like to investigate "
        "your mRNA-LNP platform rather than the usual electroporation. We intend to "
        "use this as a GMP-grade product for clinical trials.",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "I'd like to get a quote for a polyclonal antibody production from "
        "rabbit. Please let me know how to proceed.",
        {"business_line_hint": "antibody"}),
    # CAR-T context but request is xenograft sample analysis (toxicology/PK-PD/IHC) —
    # boundary case where service is outside the five core business lines.
    ("medium", "We developed CAR T cells in our startup company, and we already "
        "conducted the in vitro and vivo (xenograft) efficacy studies. Now we would "
        "like to conduct the following analyses: toxicology, PK/PD, and IHC "
        "(including images) of xenograft tumor samples. Could you please send a "
        "quote for such studies?",
        {"business_line_hint": "car_t_car_nk"}),
    # Generic "quote for selected products/services" — no specific technical signal.
    ("medium", "I am writing from cancer vaccine science, Poland, Europe. I want to "
        "know the cost or quotations of selected products and services you offer.",
        {"business_line_hint": "car_t_car_nk"}),
    ("high", "We want rabbit monoclonal antibodies that recognize the N-terminal "
        "end of histone H3 in Trypanosoma brucei only when the very N-terminus "
        "(i.e. NH3+ group of Ser1) is unmodified. I'd like a quote. "
        "Sequence: SRTKETARTK",
        {"business_line_hint": "antibody"}),
    ("high", "When producing the mRNA/LNPs are they in aqueous form? Is it possible "
        "to receive them in lyophilized or spray dried form?",
        {"business_line_hint": "mrna_lnp"}),
    # Candidate for the cold-start antibody term-mismatch pattern flagged in
    # project_rag_observation.md (doc uses "Recombinant Antibody Production",
    # customer says "human monoclonal antibodies").
    ("high", "I would like to produce human monoclonal antibodies to a few targets "
        "of my interest.",
        {"business_line_hint": "antibody"}),
    ("high", "I am looking to get a quote for synthesizing mRNA. How much will it "
        "cost to produce 1mg of 5' Capped, 100% pseudoU modified mRNA size ~3500bp? "
        "Is there a discount for synthesizing more? We have 29 designs we want to "
        "produce mRNA for, so I wanted to see if I could get a quote for 1mg and "
        "29mg for both unformulated and formulated (LNP) mRNA.",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "How long does your LNP production service usually take from start to "
        "finish? Might shipping take a while, especially having to send it from "
        "Richmond, CA to Chattanooga, TN? On a second note, would it be possible to "
        "deviate a bit from your usual services? We are trying to add dsRNA, rather "
        "than mRNA, to LNPs, and I was wondering if that could be accomplished.",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "We are interested in testing our drug product with a macrophage "
        "polarization assay to determine anti-inflammatory capabilities. Looking to "
        "see what you offer and the relative cost.",
        {"business_line_hint": "cell_based_assays"}),
    ("high", "I'm wondering if you could help us prepare lipid nanoparticle "
        "packaging of shRNA/siRNA to knockdown target genes in vitro and in vivo "
        "in mouse.",
        {"business_line_hint": "mrna_lnp"}),
    ("high", "In my laboratory we are interested in a polyclonal antibody against "
        "our bacterium. The principal purpose for this antibody is for bacterial "
        "immunostaining. For that purpose, we can send you the complete bacteria "
        "previously inactivated. Please let me know if you can develop the "
        "antibody for us.",
        {"business_line_hint": "antibody"}),
    # Investment/financing spam masquerading as a biotech inquiry — should score
    # clearly irrelevant.
    ("irrelevant", "I am contacting you on behalf of Al-Trust Investment KSC. I am "
        "a consultant to the Chairman of Al-Trust Investment KSC in Kuwait. We are "
        "ready to discuss business finance with you where partnership, loan/debt "
        "financing, equity investment can be considered depending on the "
        "profitability and structure of the business plan. Do you have a business "
        "plan we can take a look at?",
        {}),
    # Distributor partnership inquiry — commercial, not technical.
    ("low", "I'm the Director of a biomedical and life sciences sales and "
        "distribution company with presence in the South East Asia countries. I'm "
        "writing to ask if you have any distributors set up in this region already? "
        "If not, we would be keen to explore a potential partnership with your "
        "company to represent you in this region.",
        {}),
    # Co-marketing / aptamer — aptamers are outside the five core business lines.
    ("low", "I would be delighted to reinitiate conversations around aptamers as "
        "alternatives to antibodies and perhaps discussing some co-marketing "
        "opportunities.",
        {}),
    ("high", "I would like to set up a CAR mRNA-LNP delivery system for an in vivo "
        "experiment. Could you please break down the cost of each step and give me "
        "an estimate of how long the process might take?",
        {"business_line_hint": "mrna_lnp"}),
    # In-licensing inquiry with CAR-T technical keywords (T-Charge, multiple myeloma,
    # BCMA indication) — commercial intent but technically loaded.
    ("medium", "One of our multinational clients has expressed strong interest in "
        "in-licensing a CAR-T product. They are also open to exploring other CAR-T "
        "technology-based platforms, with preference for those comparable to the "
        "T-Charge platform. Their first priority is hematological indications, "
        "particularly multiple myeloma, followed by solid tumor programs in "
        "late-stage development.",
        {"business_line_hint": "car_t_car_nk"}),
]


def run_observation(csv_path: str | None = None) -> None:
    _validate_corpus(CORPUS)
    rows: list[dict[str, Any]] = []
    total = len(CORPUS)
    for idx, (category, query, ctx) in enumerate(CORPUS, start=1):
        print(f"[{idx}/{total}] ({category}) {query[:70]}", file=sys.stderr)
        result = retrieve_technical_knowledge(query=query, **ctx)
        confidence = result.get("confidence", {}) or {}
        debug = result.get("retrieval_debug", {}) or {}
        matches = result.get("matches", []) or []
        top_section = str(matches[0].get("section_type", "")) if matches else ""
        rows.append({
            "category": category,
            "query": query[:60],
            "intent_bucket": debug.get("intent_bucket", ""),
            "top_final": round(float(confidence.get("top_final_score", 0.0)), 3),
            "top_base": round(float(confidence.get("top_base_score", 0.0)), 3),
            "top_margin": round(float(confidence.get("top_margin", 0.0)), 3),
            "matches": int(confidence.get("matches_count", 0)),
            "synth": bool(confidence.get("top_is_synthesized", False)),
            "top_section": top_section[:24],
        })

    _print_table(rows)
    if csv_path:
        _export_csv(rows, csv_path)
        print(f"\nCSV exported: {csv_path}", file=sys.stderr)


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}
    sep = "-+-".join("-" * widths[h] for h in headers)
    line = " | ".join(h.ljust(widths[h]) for h in headers)
    print(line)
    print(sep)
    current_cat = None
    for r in rows:
        if current_cat is not None and r["category"] != current_cat:
            print(sep)
        current_cat = r["category"]
        print(" | ".join(str(r[h]).ljust(widths[h]) for h in headers))


def _export_csv(rows: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Optional path to export results as CSV")
    args = parser.parse_args()
    run_observation(csv_path=args.csv)
