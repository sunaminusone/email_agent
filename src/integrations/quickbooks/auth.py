import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from src.config import get_quickbooks_settings


AUTH_BASE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SANDBOX_API_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
PROD_API_BASE_URL = "https://quickbooks.api.intuit.com"


class QuickBooksConfigError(RuntimeError):
    pass


class QuickBooksAuthManager:
    def __init__(self) -> None:
        self.settings = get_quickbooks_settings()
        self.token_store = Path(self.settings["token_store"])
        self.api_base_url = (
            PROD_API_BASE_URL if self.settings["environment"] == "production" else SANDBOX_API_BASE_URL
        )

    def is_configured(self) -> bool:
        return bool(self.settings.get("is_configured"))

    def get_connection_status(self) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "configured": False,
                "connected": False,
                "environment": self.settings["environment"],
                "missing": [
                    name
                    for name, value in {
                        "QB_CLIENT_ID": self.settings["client_id"],
                        "QB_CLIENT_SECRET": self.settings["client_secret"],
                        "QB_REDIRECT_URI": self.settings["redirect_uri"],
                    }.items()
                    if not value
                ],
            }

        token_data = self._load_token_data()
        connected = bool(token_data and token_data.get("realm_id") and token_data.get("refresh_token"))
        return {
            "configured": True,
            "connected": connected,
            "environment": self.settings["environment"],
            "realm_id": token_data.get("realm_id") if token_data else None,
            "token_expires_at": token_data.get("expires_at") if token_data else None,
            "has_refresh_token": bool(token_data and token_data.get("refresh_token")),
        }

    def build_authorization_url(self, state: Optional[str] = None) -> Dict[str, str]:
        self._ensure_configured()
        state_value = state or secrets.token_urlsafe(24)
        params = {
            "client_id": self.settings["client_id"],
            "response_type": "code",
            "scope": self.settings["scope"],
            "redirect_uri": self.settings["redirect_uri"],
            "state": state_value,
        }
        query = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params.items())
        return {
            "authorization_url": f"{AUTH_BASE_URL}?{query}",
            "state": state_value,
        }

    def exchange_code(self, code: str, realm_id: str) -> Dict[str, Any]:
        self._ensure_configured()
        response = requests.post(
            TOKEN_URL,
            headers=self._token_headers(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings["redirect_uri"],
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = self._normalize_token_data(response.json(), realm_id)
        self._save_token_data(token_data)
        return token_data

    def refresh_access_token(self) -> Dict[str, Any]:
        self._ensure_configured()
        token_data = self._require_token_data()
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise QuickBooksConfigError("QuickBooks refresh token is missing. Reconnect the app.")

        response = requests.post(
            TOKEN_URL,
            headers=self._token_headers(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        updated = self._normalize_token_data(response.json(), token_data["realm_id"])
        self._save_token_data(updated)
        return updated

    def get_valid_token_data(self) -> Dict[str, Any]:
        token_data = self._require_token_data()
        expires_at = token_data.get("expires_at")
        if expires_at and self._is_expiring(expires_at):
            token_data = self.refresh_access_token()
        return token_data

    def disconnect(self) -> None:
        if self.token_store.exists():
            self.token_store.unlink()

    def _normalize_token_data(self, payload: Dict[str, Any], realm_id: str) -> Dict[str, Any]:
        expires_in = int(payload.get("expires_in", 3600))
        refresh_expires_in = int(payload.get("x_refresh_token_expires_in", 0))
        now = datetime.now(timezone.utc)
        return {
            "realm_id": realm_id,
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "token_type": payload.get("token_type", "bearer"),
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in,
            "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
            "refresh_expires_at": (now + timedelta(seconds=refresh_expires_in)).isoformat() if refresh_expires_in else None,
            "updated_at": now.isoformat(),
        }

    def _token_headers(self) -> Dict[str, str]:
        token = f"{self.settings['client_id']}:{self.settings['client_secret']}"
        encoded = base64.b64encode(token.encode("utf-8")).decode("utf-8")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _is_expiring(self, expires_at: str) -> bool:
        parsed = datetime.fromisoformat(expires_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc) + timedelta(minutes=5)

    def _load_token_data(self) -> Optional[Dict[str, Any]]:
        if not self.token_store.exists():
            return None
        return json.loads(self.token_store.read_text(encoding="utf-8"))

    def _require_token_data(self) -> Dict[str, Any]:
        token_data = self._load_token_data()
        if not token_data:
            raise QuickBooksConfigError("QuickBooks is not connected yet. Complete the OAuth flow first.")
        return token_data

    def _save_token_data(self, token_data: Dict[str, Any]) -> None:
        self.token_store.parent.mkdir(parents=True, exist_ok=True)
        self.token_store.write_text(json.dumps(token_data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_configured(self) -> None:
        if not self.is_configured():
            raise QuickBooksConfigError(
                "QuickBooks env vars are incomplete. Set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI."
            )
