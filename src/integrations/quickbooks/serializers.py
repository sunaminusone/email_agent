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
