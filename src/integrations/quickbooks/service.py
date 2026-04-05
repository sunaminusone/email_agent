from typing import Any, Dict, List, Optional

import requests

from .auth import QuickBooksAuthManager, QuickBooksConfigError
from .matching import dedupe_matches, extract_customer_matches, extract_transaction_matches, rank_customer_candidates
from .repository import QuickBooksRepository


class QuickBooksClient:
    def __init__(self) -> None:
        self.auth = QuickBooksAuthManager()
        self.repository = QuickBooksRepository(self.auth)

    def is_configured(self) -> bool:
        return self.auth.is_configured()

    def get_connection_status(self) -> Dict[str, Any]:
        return self.auth.get_connection_status()

    def build_authorization_url(self, state: Optional[str] = None) -> Dict[str, str]:
        return self.auth.build_authorization_url(state=state)

    def exchange_code(self, code: str, realm_id: str) -> Dict[str, Any]:
        return self.auth.exchange_code(code=code, realm_id=realm_id)

    def refresh_access_token(self) -> Dict[str, Any]:
        return self.auth.refresh_access_token()

    def query_transactions(
        self,
        *,
        order_numbers: Optional[List[str]] = None,
        customer_names: Optional[List[str]] = None,
        include_invoices: bool = True,
        include_sales_receipts: bool = True,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        token_data = self.auth.get_valid_token_data()
        order_numbers = [value.strip() for value in (order_numbers or []) if value and value.strip()]
        customer_names = [value.strip() for value in (customer_names or []) if value and value.strip()]
        if not order_numbers and not customer_names:
            return {
                "lookup_mode": "quickbooks",
                "status": "needs_input",
                "message": "No order numbers, invoice numbers, or customer names were extracted from the request.",
                "matches": [],
            }

        matches: List[Dict[str, Any]] = []
        searched_entities: List[str] = []
        searched_queries: List[Dict[str, str]] = []

        for entity in ["Invoice", "SalesReceipt"]:
            if entity == "Invoice" and not include_invoices:
                continue
            if entity == "SalesReceipt" and not include_sales_receipts:
                continue

            searched_entities.append(entity)
            for doc_number in order_numbers:
                response = self.repository.query_transaction_by_doc_number(
                    token_data=token_data,
                    entity=entity,
                    doc_number=doc_number,
                    max_results=max_results,
                )
                matches.extend(extract_transaction_matches(entity, response))
                searched_queries.append({"entity": entity, "mode": "doc_number", "value": doc_number})

            if matches and order_numbers:
                continue

            for customer_name in customer_names:
                response = self.repository.query_transaction_by_customer_name(
                    token_data=token_data,
                    entity=entity,
                    customer_name=customer_name,
                    max_results=max_results,
                )
                matches.extend(extract_transaction_matches(entity, response))
                searched_queries.append({"entity": entity, "mode": "customer_name", "value": customer_name})

        return {
            "lookup_mode": "quickbooks",
            "status": "completed" if matches else "not_found",
            "searched_entities": searched_entities,
            "searched_numbers": order_numbers,
            "searched_customer_names": customer_names,
            "searched_queries": searched_queries,
            "matches": dedupe_matches(matches),
        }

    def query_customers(
        self,
        *,
        customer_names: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        token_data = self.auth.get_valid_token_data()
        customer_names = [value.strip() for value in (customer_names or []) if value and value.strip()]
        if not customer_names:
            return {
                "lookup_mode": "quickbooks_customer",
                "status": "needs_input",
                "message": "No customer or lead names were extracted from the request.",
                "matches": [],
            }

        matches: List[Dict[str, Any]] = []
        searched_queries: List[Dict[str, str]] = []
        for customer_name in customer_names:
            direct_matches = self._query_customers_by_name(
                token_data=token_data,
                customer_name=customer_name,
                max_results=max_results,
                searched_queries=searched_queries,
            )
            if direct_matches:
                matches.extend(direct_matches)
                continue

            fallback_matches = self._search_customers_locally(
                token_data=token_data,
                customer_name=customer_name,
                max_results=max_results,
                searched_queries=searched_queries,
            )
            matches.extend(fallback_matches)

        return {
            "lookup_mode": "quickbooks_customer",
            "status": "completed" if matches else "not_found",
            "searched_customer_names": customer_names,
            "searched_queries": searched_queries,
            "matches": dedupe_matches(matches),
        }

    def disconnect(self) -> None:
        self.auth.disconnect()

    def _query_customers_by_name(
        self,
        *,
        token_data: Dict[str, Any],
        customer_name: str,
        max_results: int,
        searched_queries: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for field in ["DisplayName", "CompanyName", "FullyQualifiedName"]:
            try:
                response = self.repository.query_customer_by_field(
                    token_data=token_data,
                    field=field,
                    customer_name=customer_name,
                    max_results=max_results,
                )
            except requests.HTTPError:
                searched_queries.append({"entity": "Customer", "mode": f"{field}_error", "value": customer_name})
                continue

            field_matches = extract_customer_matches(response)
            searched_queries.append({"entity": "Customer", "mode": field, "value": customer_name})
            if field_matches:
                matches.extend(field_matches)
                break

        return matches

    def _search_customers_locally(
        self,
        *,
        token_data: Dict[str, Any],
        customer_name: str,
        max_results: int,
        searched_queries: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        response = self.repository.query_customer_scan(token_data=token_data, max_results=max_results)
        searched_queries.append({"entity": "Customer", "mode": "local_fuzzy_scan", "value": customer_name})
        candidates = extract_customer_matches(response)
        return rank_customer_candidates(candidates, customer_name, max_results)
