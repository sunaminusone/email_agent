"""QuickBooks sandbox config + token refresh smoke.

Catches the two quiet failure modes for QB:
- env-var rot (QB_CLIENT_ID / QB_CLIENT_SECRET / QB_REDIRECT_URI dropped
  or rotated without updating .env), and
- refresh-token revocation (Intuit invalidates the saved refresh_token
  after a long idle window or sandbox reset, and the next CSR query
  fails with an opaque OAuth 401).

Defensive guard refuses to run against production — these tests
exercise the live Intuit OAuth endpoint and mutate the on-disk token
store, which is fine for sandbox but not for prod.

Run with ``pytest tests/test_integration_quickbooks_smoke.py --integration``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.integrations.quickbooks.auth import QuickBooksAuthManager

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def auth_manager() -> QuickBooksAuthManager:
    manager = QuickBooksAuthManager()
    if manager.settings["environment"] != "sandbox":
        pytest.skip(
            "refusing to run live QuickBooks tests outside sandbox; "
            f"current QB_ENVIRONMENT={manager.settings['environment']!r}"
        )
    return manager


def test_quickbooks_env_configured(auth_manager: QuickBooksAuthManager) -> None:
    assert auth_manager.is_configured(), (
        "QB_CLIENT_ID / QB_CLIENT_SECRET / QB_REDIRECT_URI missing in .env"
    )


def test_token_store_parses(auth_manager: QuickBooksAuthManager) -> None:
    store = Path(auth_manager.token_store)
    if not store.exists():
        pytest.skip(f"token store {store} not present; run OAuth flow first")
    data = json.loads(store.read_text(encoding="utf-8"))
    assert data.get("realm_id"), "token store missing realm_id"
    assert data.get("refresh_token"), "token store missing refresh_token"


def test_connection_status_reports_connected(
    auth_manager: QuickBooksAuthManager,
) -> None:
    status = auth_manager.get_connection_status()
    assert status["configured"] is True
    assert status["environment"] == "sandbox"
    assert status["connected"] is True, status
    assert status.get("realm_id"), status


def test_refresh_access_token_round_trip(
    auth_manager: QuickBooksAuthManager,
) -> None:
    if not Path(auth_manager.token_store).exists():
        pytest.skip("token store not present; run OAuth flow first")
    refreshed = auth_manager.refresh_access_token()
    assert refreshed.get("access_token"), "refresh returned no access_token"
    assert refreshed.get("refresh_token"), "refresh returned no refresh_token"
    assert refreshed.get("realm_id"), "refresh dropped realm_id"
