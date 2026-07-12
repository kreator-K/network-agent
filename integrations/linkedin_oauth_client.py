"""LinkedIn authorization-code OAuth foundation for Phase 8G-B1.

This module authenticates against LinkedIn's official OAuth endpoints only. It
does not read feeds, scrape profiles, send messages, or publish content.
Tokens are encrypted with a Fernet key before they are written to disk.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken


LINKEDIN_SCOPES = ("openid", "profile", "w_member_social")
AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


class LinkedInOAuthError(RuntimeError):
    """Controlled LinkedIn OAuth or token-storage failure."""


@dataclass(frozen=True)
class LinkedInTokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scope: str


class LinkedInOAuthClient:
    """Authorization-code client with encrypted local token persistence."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        encryption_key: str,
        token_path: str | Path,
        http_session: Any = requests,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._fernet = self._build_fernet(encryption_key)
        self.token_path = Path(token_path)
        self.http_session = http_session

    def authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Return the consent URL and CSRF state for the allowlisted scopes."""
        if not self.client_id or not self.redirect_uri:
            raise LinkedInOAuthError("LinkedIn OAuth client ID and redirect URI are required.")
        csrf_state = state or secrets.token_urlsafe(32)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "state": csrf_state,
                "scope": " ".join(LINKEDIN_SCOPES),
            }
        )
        return f"{AUTHORIZATION_URL}?{query}", csrf_state

    def exchange_code(self, code: str, *, state_valid: bool = True) -> LinkedInTokenSet:
        """Exchange one callback code and persist only its encrypted token set."""
        if not code.strip() or not state_valid:
            raise LinkedInOAuthError("LinkedIn OAuth callback validation failed.")
        response = self.http_session.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise LinkedInOAuthError("LinkedIn OAuth token exchange failed.")
        try:
            payload = response.json()
            access_token = payload["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LinkedInOAuthError("LinkedIn OAuth returned an invalid token response.") from exc
        token_set = LinkedInTokenSet(
            access_token=str(access_token),
            refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
            expires_in=int(payload["expires_in"]) if payload.get("expires_in") is not None else None,
            scope=str(payload.get("scope") or " ".join(LINKEDIN_SCOPES)),
        )
        self.save_tokens(token_set)
        return token_set

    def save_tokens(self, tokens: LinkedInTokenSet) -> None:
        """Encrypt token material before writing it to the configured path."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(tokens.__dict__, sort_keys=True).encode("utf-8")
        self.token_path.write_bytes(self._fernet.encrypt(plaintext))

    def load_tokens(self) -> LinkedInTokenSet:
        """Load and decrypt the locally stored token set."""
        try:
            payload = json.loads(self._fernet.decrypt(self.token_path.read_bytes()))
            return LinkedInTokenSet(
                access_token=str(payload["access_token"]),
                refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
                expires_in=int(payload["expires_in"]) if payload.get("expires_in") is not None else None,
                scope=str(payload["scope"]),
            )
        except (OSError, InvalidToken, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LinkedInOAuthError("Stored LinkedIn OAuth tokens could not be decrypted.") from exc

    @staticmethod
    def _build_fernet(key: str) -> Fernet:
        if not key.strip():
            raise LinkedInOAuthError("LINKEDIN_TOKEN_ENCRYPTION_KEY is required.")
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise LinkedInOAuthError("LINKEDIN_TOKEN_ENCRYPTION_KEY is invalid.") from exc
