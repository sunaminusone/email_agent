from typing import Any, Dict

import requests

from .auth import QuickBooksAuthManager, QuickBooksConfigError


class QuickBooksQueryClient:
    def __init__(self, auth: QuickBooksAuthManager) -> None:
        self.auth = auth

    def execute_query(self, query: str, token_data: Dict[str, Any]) -> Dict[str, Any]:
        realm_id = token_data.get("realm_id")
        if not realm_id:
            raise QuickBooksConfigError("QuickBooks realm_id is missing. Reconnect the app.")

        response = requests.get(
            f"{self.auth.api_base_url}/v3/company/{realm_id}/query",
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Accept": "application/json",
            },
            params={"query": query},
            timeout=30,
        )
        if response.status_code == 401:
            refreshed = self.auth.refresh_access_token()
            response = requests.get(
                f"{self.auth.api_base_url}/v3/company/{realm_id}/query",
                headers={
                    "Authorization": f"Bearer {refreshed['access_token']}",
                    "Accept": "application/json",
                },
                params={"query": query},
                timeout=30,
            )
        response.raise_for_status()
        return response.json()

    def query_transaction_by_doc_number(
        self,
        *,
        token_data: Dict[str, Any],
        entity: str,
        doc_number: str,
        max_results: int,
    ) -> Dict[str, Any]:
        query = f"select * from {entity} where DocNumber = '{self._escape_value(doc_number)}' maxresults {max_results}"
        return self.execute_query(query, token_data)

    def query_transaction_by_customer_name(
        self,
        *,
        token_data: Dict[str, Any],
        entity: str,
        customer_name: str,
        max_results: int,
    ) -> Dict[str, Any]:
        query = (
            f"select * from {entity} where CustomerRef.name = '{self._escape_value(customer_name)}' "
            f"maxresults {max_results}"
        )
        return self.execute_query(query, token_data)

    def query_customer_by_field(
        self,
        *,
        token_data: Dict[str, Any],
        field: str,
        customer_name: str,
        max_results: int,
    ) -> Dict[str, Any]:
        query = (
            f"select * from Customer where {field} = '{self._escape_value(customer_name)}' "
            f"maxresults {max_results}"
        )
        return self.execute_query(query, token_data)

    def query_customer_scan(
        self,
        *,
        token_data: Dict[str, Any],
        max_results: int,
    ) -> Dict[str, Any]:
        query = f"select * from Customer startposition 1 maxresults {max(max_results * 5, 50)}"
        return self.execute_query(query, token_data)

    @staticmethod
    def _escape_value(value: str) -> str:
        return value.replace("'", "\\'")
