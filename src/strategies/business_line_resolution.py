from __future__ import annotations

import re
from typing import Any


CUSTOM_ACTION_STRONG = {
    "customize", "customized", "tailor", "tailored", "engineer", "engineering",
    "optimize", "optimization", "modify", "reformulate", "humanize", "conjugate",
}

CUSTOM_ACTION_WEAK = {
    "design", "develop", "building", "build", "generate", "preparing", "prepare", "evaluate",
}

CUSTOM_OBJECT_STRONG = {
    "construct", "vector", "scfv", "car construct", "cell line", "lnp formulation",
    "payload", "sequence", "antibody humanization", "conjugate", "lentiviral vector",
}

CUSTOM_OBJECT_WEAK = {
    "assay", "panel", "workflow", "delivery system", "formulation", "target", "mrna",
}

CUSTOM_NEGATIVE = {
    "price", "quote", "lead time", "availability", "catalog number", "catalog no",
    "datasheet", "coa", "sds", "brochure", "order", "invoice", "shipping", "in stock",
}

CUSTOM_PHRASES_STRONG = {
    "custom construct", "custom formulation", "custom synthesis", "tailored solution",
    "engineering service", "project scoping", "feasibility study", "assay development",
    "vector design", "construct design", "sequence optimization", "payload optimization",
    "conjugation service", "humanization service", "screening service",
}


def _safe_request_flags(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("request_flags", {})


def _safe_product_lookup_keys(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("product_lookup_keys", {})



def _safe_routing_memory(agent_input: dict[str, Any]) -> dict[str, Any]:
    return agent_input.get("routing_memory", {})


def normalize_resolution_text(text: str) -> str:
    normalized = text.lower()
    replacements = {
        "car-t": " car_t ",
        "car t": " car_t ",
        "cart ": " car_t ",
        "cart,": " car_t ,",
        "cart.": " car_t .",
        "cart?": " car_t ?",
        "car-nk": " car_nk ",
        "car nk": " car_nk ",
        "mrna-lnp": " mrna_lnp ",
        "mrna lnp": " mrna_lnp ",
        "lnp mrna": " mrna_lnp ",
        "m r n a": " mrna ",
        "l n p": " lnp ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def combined_resolution_text(agent_input: dict[str, Any]) -> str:
    parts = [
        agent_input.get("original_email_text", ""),
        agent_input.get("effective_query", ""),
        agent_input.get("query", ""),
        " ".join(agent_input.get("entities", {}).get("product_names", [])),
        " ".join(agent_input.get("entities", {}).get("targets", [])),
        " ".join(agent_input.get("entities", {}).get("service_names", [])),
        " ".join(agent_input.get("retrieval_hints", {}).get("keywords", [])),
    ]
    return normalize_resolution_text(" ".join(part for part in parts if part))


def _contains_any(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term in text)


def _match_terms(text: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in text)


def score_customization(text: str) -> dict[str, Any]:
    strong_phrases = _match_terms(text, CUSTOM_PHRASES_STRONG)
    action_strong = _match_terms(text, CUSTOM_ACTION_STRONG)
    action_weak = _match_terms(text, CUSTOM_ACTION_WEAK)
    object_strong = _match_terms(text, CUSTOM_OBJECT_STRONG)
    object_weak = _match_terms(text, CUSTOM_OBJECT_WEAK)
    negative = _match_terms(text, CUSTOM_NEGATIVE)

    score = 0
    if strong_phrases:
        score += 4
    if action_strong:
        score += 3
    elif action_weak:
        score += 1
    if object_strong:
        score += 3
    elif object_weak:
        score += 1
    if (action_strong or action_weak) and (object_strong or object_weak):
        score += 2
    if action_strong and object_strong:
        score += 2
    score -= min(len(negative), 3)

    return {
        "score": score,
        "strong_phrases": strong_phrases,
        "action_strong": action_strong,
        "action_weak": action_weak,
        "object_strong": object_strong,
        "object_weak": object_weak,
        "negative": negative,
    }


def _score_antibody_context(text: str) -> int:
    score = 0
    if "anti-" in text and "antibody" in text:
        score += 2
    if re.search(r"anti-[a-z0-9+/ -]+ antibody", text):
        score += 3
    if any(term in text for term in ["secondary antibody", "tag antibody", "monoclonal antibody", "polyclonal antibody"]):
        score += 2
    if "anti-" in text and any(term in text for term in ["car", "car_t", "scfv", "cd3z", "4-1bb", "cd28"]):
        score -= 2
    return score


def _score_business_lines(agent_input: dict[str, Any]) -> dict[str, int]:
    text = combined_resolution_text(agent_input)
    product_lookup_keys = _safe_product_lookup_keys(agent_input)
    catalog_numbers = " ".join(product_lookup_keys.get("catalog_numbers", [])).lower()

    scores = {
        "car_t": 0,
        "mrna_lnp": 0,
        "antibody": 0,
    }

    car_t_terms = [
        "car_t", "car_nk", "car immune", "lentivirus", "lentiviral", "pbmc",
        "target cell line", "activation beads", "scfv", "costimulatory",
        "cd3z", "4-1bb", "cd28", "immune cell", "t cell", "nk cell",
    ]
    mrna_lnp_terms = [
        "mrna_lnp", "mrna", "lnp", "lipid nanoparticle", "transfection",
        "formulation", "encapsulation", "gene delivery", "protein expression",
        "toxicity", "cargo",
    ]
    antibody_terms = [
        "antibody", "antibodies", "monoclonal", "polyclonal", "secondary antibody",
        "rabbit polyclonal", "mouse monoclonal", "igg", "isotype", "clone",
        "tag antibody", "epitope tag", "wb", "ihc", "icc", "fcm",
    ]

    scores["car_t"] += _contains_any(text, car_t_terms) * 2
    scores["mrna_lnp"] += _contains_any(text, mrna_lnp_terms) * 2
    scores["antibody"] += _contains_any(text, antibody_terms) * 2
    scores["antibody"] += _score_antibody_context(text)

    if "pm-car" in text or "pm-car" in catalog_numbers:
        scores["car_t"] += 6
    if "pm-lnp" in text or "pm-lnp" in catalog_numbers:
        scores["mrna_lnp"] += 6
    if any(term in text for term in ["flag tag", "his tag", "ha tag", "c-myc tag", "6×his", "6xhis"]):
        scores["antibody"] += 4
    if any(term in text for term in ["elisa", "western blot", "wb", "ihc", "icc", "fcm", "flow cytometry"]):
        scores["antibody"] += 2
    if any(term in text for term in ["anti-bcma car", "anti-cd19 car", "anti-her2 car"]):
        scores["car_t"] += 2
        scores["mrna_lnp"] += 2
    if "anti-" in text and any(term in text for term in ["car", "car_t", "scfv", "cd3z", "4-1bb", "cd28"]):
        scores["car_t"] += 2
    if any(term in text for term in ["delivery", "transgene", "encapsulation", "formulation"]):
        scores["mrna_lnp"] += 2

    return scores


def _business_line_signal(agent_input: dict[str, Any]) -> dict[str, Any]:
    scores = _score_business_lines(agent_input)
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_line, top_score = sorted_scores[0]
    second_line, second_score = sorted_scores[1]
    gap = top_score - second_score
    return {
        "scores": scores,
        "top_line": top_line,
        "top_score": top_score,
        "second_line": second_line,
        "second_score": second_score,
        "gap": gap,
        "is_gray_zone": top_score == 0 or (second_score > 0 and gap <= 1),
        "confidence_band": (
            "low"
            if top_score == 0
            else "medium"
            if second_score > 0 and gap <= 1
            else "high"
        ),
    }


def detect_business_line(agent_input: dict[str, Any]) -> str:
    signal = _business_line_signal(agent_input)
    if signal["top_score"] == 0:
        return "unknown"
    if signal["top_score"] > 0 and signal["second_score"] > 0 and abs(signal["top_score"] - signal["second_score"]) <= 1:
        return "cross_line"
    return signal["top_line"]


def detect_engagement_type(agent_input: dict[str, Any], business_line: str) -> str:
    text = combined_resolution_text(agent_input)
    request_flags = _safe_request_flags(agent_input)
    catalog_terms = [
        "catalog", "catalog no", "catalog number", "pm-car", "pm-lnp", "price", "quote",
        "bulk purchase", "available", "in stock",
    ]
    custom_signals = score_customization(text)

    if request_flags.get("needs_customization"):
        return "custom_service"
    if custom_signals["score"] >= 6:
        return "custom_service"
    if any(term in text for term in catalog_terms):
        return "catalog_product"
    if request_flags.get("needs_price") or request_flags.get("needs_quote") or request_flags.get("needs_availability"):
        return "catalog_product"
    return "general_inquiry"


def gray_zone_reasons(
    agent_input: dict[str, Any],
    business_line: str,
    engagement_type: str,
    custom_signals: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    request_flags = _safe_request_flags(agent_input)
    intent = agent_input.get("context", {}).get("semantic_intent", "unknown")

    if 4 <= custom_signals["score"] <= 5 and not request_flags.get("needs_customization"):
        reasons.append("customization_borderline")
    if engagement_type == "custom_service" and custom_signals["negative"] and not request_flags.get("needs_customization"):
        reasons.append("customization_has_operational_signals")
    if intent in {"technical_question", "troubleshooting"} and custom_signals["score"] >= 5 and not request_flags.get("needs_customization"):
        reasons.append("technical_vs_customization_overlap")
    return reasons


def build_routing_debug_info(agent_input: dict[str, Any]) -> dict[str, Any]:
    business_line = detect_business_line(agent_input)
    engagement_type = detect_engagement_type(agent_input, business_line)
    custom_signals = score_customization(combined_resolution_text(agent_input))
    business_line_signal = _business_line_signal(agent_input)
    debug_gray_zone_reasons = gray_zone_reasons(agent_input, business_line, engagement_type, custom_signals)

    return {
        "business_line": business_line,
        "engagement_type": engagement_type,
        "business_line_scores": business_line_signal["scores"],
        "business_line_top": business_line_signal["top_line"],
        "business_line_second": business_line_signal["second_line"],
        "business_line_gap": business_line_signal["gap"],
        "business_line_confidence": business_line_signal["confidence_band"],
        "customization_score": custom_signals["score"],
        "customization_signals": {
            "strong_phrases": custom_signals["strong_phrases"],
            "action_strong": custom_signals["action_strong"],
            "action_weak": custom_signals["action_weak"],
            "object_strong": custom_signals["object_strong"],
            "object_weak": custom_signals["object_weak"],
            "negative": custom_signals["negative"],
        },
        "gray_zone_reasons": debug_gray_zone_reasons,
        "is_gray_zone": bool(debug_gray_zone_reasons),
        "routing_memory": _safe_routing_memory(agent_input),
    }
