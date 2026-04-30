import logging
from typing import Any, Dict, List, Optional

import requests

from .auth import QuickBooksAuthManager, QuickBooksConfigError
from .client import QuickBooksQueryClient
from .ranking import dedupe_matches, rank_customer_candidates
from .serializers import extract_customer_matches, extract_transaction_matches

logger = logging.getLogger(__name__)


class QuickBooksClient:
    def __init__(self) -> None:
        self.auth = QuickBooksAuthManager()
        self.client = QuickBooksQueryClient(self.auth)

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
        errors: List[str] = []

        for entity in ["Invoice", "SalesReceipt"]:
            if entity == "Invoice" and not include_invoices:
                continue
            if entity == "SalesReceipt" and not include_sales_receipts:
                continue

            searched_entities.append(entity)
            for doc_number in order_numbers:
                try:
                    response = self.client.query_transaction_by_doc_number(
                        token_data=token_data,
                        entity=entity,
                        doc_number=doc_number,
                        max_results=max_results,
                    )
                    matches.extend(extract_transaction_matches(entity, response))
                    searched_queries.append({"entity": entity, "mode": "doc_number", "value": doc_number})
                except requests.RequestException as exc:
                    logger.warning("QuickBooks %s query failed for doc_number=%s: %s", entity, doc_number, exc)
                    searched_queries.append({"entity": entity, "mode": "doc_number_error", "value": doc_number})
                    errors.append(f"{entity} lookup by doc_number '{doc_number}' failed: {exc}")

            if matches and order_numbers:
                continue

            for customer_name in customer_names:
                try:
                    response = self.client.query_transaction_by_customer_name(
                        token_data=token_data,
                        entity=entity,
                        customer_name=customer_name,
                        max_results=max_results,
                    )
                    matches.extend(extract_transaction_matches(entity, response))
                    searched_queries.append({"entity": entity, "mode": "customer_name", "value": customer_name})
                except requests.RequestException as exc:
                    logger.warning("QuickBooks %s query failed for customer=%s: %s", entity, customer_name, exc)
                    searched_queries.append({"entity": entity, "mode": "customer_name_error", "value": customer_name})
                    errors.append(f"{entity} lookup by customer '{customer_name}' failed: {exc}")

        if matches and errors:
            status = "partial"
        elif matches:
            status = "completed"
        elif errors:
            status = "error"
        else:
            status = "not_found"
        result: Dict[str, Any] = {
            "lookup_mode": "quickbooks",
            "status": status,
            "searched_entities": searched_entities,
            "searched_numbers": order_numbers,
            "searched_customer_names": customer_names,
            "searched_queries": searched_queries,
            "matches": dedupe_matches(matches),
        }
        if errors:
            result["errors"] = errors
        return result

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
        errors: List[str] = []
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
                errors=errors,
            )
            matches.extend(fallback_matches)

        status = "completed" if matches else ("error" if errors and not matches else "not_found")
        result: Dict[str, Any] = {
            "lookup_mode": "quickbooks_customer",
            "status": status,
            "searched_customer_names": customer_names,
            "searched_queries": searched_queries,
            "matches": dedupe_matches(matches),
        }
        if errors:
            result["errors"] = errors
        return result

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
                response = self.client.query_customer_by_field(
                    token_data=token_data,
                    field=field,
                    customer_name=customer_name,
                    max_results=max_results,
                )
            except requests.RequestException as exc:
                logger.warning("QuickBooks Customer query failed for %s=%s: %s", field, customer_name, exc)
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
        errors: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        try:
            response = self.client.query_customer_scan(token_data=token_data, max_results=max_results)
        except requests.RequestException as exc:
            logger.warning("QuickBooks customer scan failed: %s", exc)
            searched_queries.append({"entity": "Customer", "mode": "local_fuzzy_scan_error", "value": customer_name})
            if errors is not None:
                errors.append(f"Customer scan for '{customer_name}' failed: {exc}")
            return []
        searched_queries.append({"entity": "Customer", "mode": "local_fuzzy_scan", "value": customer_name})
        candidates = extract_customer_matches(response)
        return rank_customer_candidates(candidates, customer_name, max_results)
