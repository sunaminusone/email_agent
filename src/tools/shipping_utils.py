from typing import Any, Dict, List


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def filter_shipping_matches(
    matches: List[Dict[str, Any]],
    destination: str | None,
) -> List[Dict[str, Any]]:
    if not destination:
        return matches

    normalized_destination = _normalize_text(destination)
    destination_tokens = [token for token in normalized_destination.replace(",", " ").split() if token]
    if not destination_tokens:
        return matches

    filtered = []
    for match in matches:
        haystack = _normalize_text(
            " ".join(
                str(part or "")
                for part in [
                    match.get("ship_city"),
                    match.get("ship_country"),
                    match.get("customer_name"),
                    match.get("doc_number"),
                ]
            )
        )
        if all(token in haystack for token in destination_tokens):
            filtered.append(match)

    return filtered or matches
