import re
from typing import Any, Dict, List


def extract_transaction_matches(entity: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_response = payload.get("QueryResponse", {})
    rows = query_response.get(entity, [])
    if isinstance(rows, dict):
        rows = [rows]

    matches: List[Dict[str, Any]] = []
    for row in rows:
        metadata = row.get("MetaData", {})
        ship_addr = row.get("ShipAddr", {}) or {}
        bill_email = row.get("BillEmail", {}) or {}
        customer_ref = row.get("CustomerRef", {}) or {}
        matches.append(
            {
                "entity": entity,
                "id": row.get("Id"),
                "doc_number": row.get("DocNumber"),
                "txn_date": row.get("TxnDate"),
                "due_date": row.get("DueDate"),
                "ship_date": row.get("ShipDate"),
                "email_status": row.get("EmailStatus"),
                "print_status": row.get("PrintStatus"),
                "balance": row.get("Balance"),
                "total_amt": row.get("TotalAmt"),
                "customer_name": customer_ref.get("name"),
                "customer_id": customer_ref.get("value"),
                "billing_email": bill_email.get("Address"),
                "ship_city": ship_addr.get("City"),
                "ship_country": ship_addr.get("Country"),
                "last_updated_at": metadata.get("LastUpdatedTime"),
                "raw": row,
            }
        )
    return matches


def extract_customer_matches(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_response = payload.get("QueryResponse", {})
    rows = query_response.get("Customer", [])
    if isinstance(rows, dict):
        rows = [rows]

    matches: List[Dict[str, Any]] = []
    for row in rows:
        primary_phone = row.get("PrimaryPhone", {}) or {}
        mobile = row.get("Mobile", {}) or {}
        primary_email = row.get("PrimaryEmailAddr", {}) or {}
        bill_addr = row.get("BillAddr", {}) or {}
        ship_addr = row.get("ShipAddr", {}) or {}
        matches.append(
            {
                "entity": "Customer",
                "id": row.get("Id"),
                "display_name": row.get("DisplayName"),
                "company_name": row.get("CompanyName"),
                "fully_qualified_name": row.get("FullyQualifiedName"),
                "primary_phone": primary_phone.get("FreeFormNumber"),
                "mobile_phone": mobile.get("FreeFormNumber"),
                "primary_email": primary_email.get("Address"),
                "open_balance": row.get("Balance") if row.get("Balance") is not None else row.get("OpenBalance"),
                "balance": row.get("Balance"),
                "active": row.get("Active"),
                "notes": row.get("Notes"),
                "bill_addr": bill_addr,
                "ship_addr": ship_addr,
                "raw": row,
            }
        )
    return matches


def rank_customer_candidates(candidates: List[Dict[str, Any]], customer_name: str, max_results: int) -> List[Dict[str, Any]]:
    normalized_target = normalize_customer_name(customer_name)
    target_tokens = set(customer_name_tokens(customer_name))
    ranked: List[tuple[int, Dict[str, Any]]] = []

    for candidate in candidates:
        score = 0
        names_to_compare = [
            candidate.get("display_name"),
            candidate.get("company_name"),
            candidate.get("fully_qualified_name"),
        ]
        normalized_variants = [normalize_customer_name(name) for name in names_to_compare if name]
        token_variants = [set(customer_name_tokens(name)) for name in names_to_compare if name]

        if normalized_target in normalized_variants:
            score += 100

        for normalized_variant in normalized_variants:
            if normalized_target and normalized_target in normalized_variant:
                score += 40
            if normalized_variant and normalized_variant in normalized_target:
                score += 25

        for tokens in token_variants:
            overlap = len(target_tokens.intersection(tokens))
            if overlap:
                score += overlap * 10

        if score > 0:
            ranked.append((score, candidate))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked[:max_results]]


def dedupe_matches(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for match in matches:
        key = (match.get("entity"), match.get("id"), match.get("doc_number"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return deduped


def normalize_customer_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def customer_name_tokens(value: str) -> List[str]:
    normalized = normalize_customer_name(value)
    return [token for token in normalized.split() if token]
