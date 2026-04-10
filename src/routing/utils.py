from __future__ import annotations


def normalize_routing_text(text: str) -> str:
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


def contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)
