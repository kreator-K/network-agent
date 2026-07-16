"""LinkedIn authorization-code OAuth foundation for Phase 8G-B1.

This module authenticates against LinkedIn's official OAuth endpoints only. It
does not read feeds, scrape profiles, send messages, or publish content.
Tokens are encrypted with a Fernet key before they are written to disk.
"""

from __future__ import annotations

import json
import secrets
import base64
import time
import hashlib
import sqlite3
import re
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken


LINKEDIN_SCOPES = ("openid", "profile", "w_member_social")
AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
INTROSPECTION_URL = "https://www.linkedin.com/oauth/v2/introspectToken"


class LinkedInOAuthError(RuntimeError):
    """Controlled LinkedIn OAuth or token-storage failure."""


@dataclass(frozen=True)
class LinkedInTokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scope: str
    id_token: str | None = None
    scope_field_present: bool = True
    raw_scope_type: str = "str"
    scope_source: str = "token_response"
    introspection_attempted: bool = False


def normalize_linkedin_scopes(raw_scopes: Any) -> set[str]:
    """Normalize LinkedIn token or introspection scope representations."""
    if raw_scopes is None:
        return set()
    if isinstance(raw_scopes, (list, tuple, set, frozenset)):
        normalized: set[str] = set()
        for item in raw_scopes:
            normalized.update(normalize_linkedin_scopes(item))
        return normalized
    if not isinstance(raw_scopes, str):
        return set()
    decoded = unquote_plus(raw_scopes).strip()
    return {part for part in re.split(r"[\s,]+", decoded) if part}


def serialize_linkedin_scopes(scopes: set[str]) -> str:
    ordered = [scope for scope in LINKEDIN_SCOPES if scope in scopes]
    ordered.extend(sorted(scopes.difference(LINKEDIN_SCOPES)))
    return " ".join(ordered)


@dataclass(frozen=True)
class LinkedInOAuthState:
    state: str
    telegram_user_id: str
    telegram_chat_id: str
    expires_at: str
    requested_scopes: str
    redirect_uri: str


class LinkedInOAuthStateStore:
    """SQLite-backed, one-time OAuth state repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @staticmethod
    def _hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def create(
        self, *, telegram_user_id: str, telegram_chat_id: str,
        scopes: str, redirect_uri: str, ttl_seconds: int,
    ) -> LinkedInOAuthState:
        raw_state = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        expires_at = expires.isoformat()
        self.connection.execute(
            """INSERT INTO linkedin_oauth_states
            (state_hash, telegram_user_id, telegram_chat_id, status, expires_at,
             created_at, requested_scopes, redirect_uri)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (self._hash(raw_state), str(telegram_user_id), str(telegram_chat_id),
             expires_at, datetime.now(UTC).isoformat(), scopes, redirect_uri),
        )
        self.connection.commit()
        return LinkedInOAuthState(raw_state, str(telegram_user_id), str(telegram_chat_id), expires_at, scopes, redirect_uri)

    def consume(self, state: str) -> sqlite3.Row:
        if not state.strip():
            raise LinkedInOAuthError("unknown_state")
        now = datetime.now(UTC).isoformat()
        row = self.connection.execute(
            "SELECT * FROM linkedin_oauth_states WHERE state_hash = ?", (self._hash(state),)
        ).fetchone()
        if row is None:
            raise LinkedInOAuthError("unknown_state")
        if row["status"] != "pending":
            raise LinkedInOAuthError(f"{row['status']}_state")
        if row["expires_at"] <= now:
            self.connection.execute(
                "UPDATE linkedin_oauth_states SET status='expired' WHERE id=?", (row["id"],)
            )
            self.connection.commit()
            raise LinkedInOAuthError("expired_state")
        updated = self.connection.execute(
            "UPDATE linkedin_oauth_states SET status='consumed', consumed_at=? WHERE id=? AND status='pending'",
            (now, row["id"]),
        ).rowcount
        self.connection.commit()
        if updated != 1:
            raise LinkedInOAuthError("consumed_state")
        return row

    def cancel_pending(self) -> int:
        result = self.connection.execute(
            "UPDATE linkedin_oauth_states SET status='cancelled' WHERE status='pending'", ()
        )
        self.connection.commit()
        return result.rowcount

    def mark_failed(self, state_id: int, *, stage: str = "callback", reason: str = "oauth_callback_failed", correlation_id: str | None = None) -> None:
        self.connection.execute(
            "UPDATE linkedin_oauth_states SET status='failed', failure_stage=?, error_summary=?, correlation_id=? WHERE id=? AND status='consumed'",
            (stage[:80], reason[:240], correlation_id, state_id),
        )
        self.connection.commit()

    def record_scope_diagnostics(
        self, state_id: int, *, granted_scopes: str, missing_scopes: str,
        unexpected_scopes: str, raw_scope_type: str, scope_field_present: bool,
        introspection_attempted: bool,
    ) -> None:
        self.connection.execute(
            """UPDATE linkedin_oauth_states SET granted_scopes=?, missing_scopes=?,
            unexpected_scopes=?, raw_scope_type=?, scope_field_present=?,
            introspection_attempted=? WHERE id=?""",
            (granted_scopes, missing_scopes, unexpected_scopes, raw_scope_type[:40],
             int(scope_field_present), int(introspection_attempted), state_id),
        )
        self.connection.commit()

    def expire_stale(self) -> int:
        result = self.connection.execute(
            "UPDATE linkedin_oauth_states SET status='expired' WHERE status='pending' AND expires_at <= ?",
            (datetime.now(UTC).isoformat(),),
        )
        self.connection.commit()
        return result.rowcount

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, status, requested_scopes, created_at, expires_at, consumed_at, failure_stage, error_summary, correlation_id FROM linkedin_oauth_states ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


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
        scopes: str = "openid profile w_member_social",
        timeout_seconds: int = 20,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._fernet = self._build_fernet(encryption_key)
        self.token_path = Path(token_path)
        self.http_session = http_session
        requested = tuple(scopes.split())
        if set(requested) != set(LINKEDIN_SCOPES):
            raise LinkedInOAuthError("LinkedIn OAuth scopes exceed the allowlist.")
        self.scopes = requested
        self.timeout_seconds = timeout_seconds

    def authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Return the consent URL and CSRF state for the allowlisted scopes."""
        if not self.client_id or not self.redirect_uri:
            raise LinkedInOAuthError("LinkedIn OAuth client ID and redirect URI are required.")
        if not self.redirect_uri.startswith("https://"):
            raise LinkedInOAuthError("LinkedIn redirect URI must use HTTPS.")
        csrf_state = state or secrets.token_urlsafe(32)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "state": csrf_state,
                "scope": " ".join(self.scopes),
            }
        )
        return f"{AUTHORIZATION_URL}?{query}", csrf_state

    def exchange_code(self, code: str, *, state_valid: bool = True, persist_tokens: bool = True) -> LinkedInTokenSet:
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
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise LinkedInOAuthError("LinkedIn OAuth token exchange failed.")
        try:
            payload = response.json()
            access_token = payload["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LinkedInOAuthError("LinkedIn OAuth returned an invalid token response.") from exc
        raw_scope = payload.get("scope")
        scope_field_present = "scope" in payload and raw_scope is not None
        granted_scopes = normalize_linkedin_scopes(raw_scope)
        introspection_attempted = False
        scope_source = "token_response"
        if not granted_scopes:
            introspection_attempted = True
            granted_scopes = self.introspect_token(str(access_token))
            scope_source = "introspection"
        token_set = LinkedInTokenSet(
            access_token=str(access_token),
            refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
            expires_in=int(payload["expires_in"]) if payload.get("expires_in") is not None else None,
            scope=serialize_linkedin_scopes(granted_scopes),
            id_token=str(payload["id_token"]) if payload.get("id_token") else None,
            scope_field_present=scope_field_present,
            raw_scope_type=type(raw_scope).__name__,
            scope_source=scope_source,
            introspection_attempted=introspection_attempted,
        )
        if persist_tokens:
            self.save_tokens(token_set)
        return token_set

    def introspect_token(self, access_token: str) -> set[str]:
        """Resolve scopes only when the token response omitted usable scope data."""
        try:
            response = self.http_session.post(
                INTROSPECTION_URL,
                data={"client_id": self.client_id, "client_secret": self.client_secret, "token": access_token},
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise LinkedInOAuthError("LinkedIn token introspection timed out.") from exc
        if response.status_code != 200:
            raise LinkedInOAuthError("LinkedIn token introspection failed.")
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise LinkedInOAuthError("LinkedIn token introspection response is malformed.") from exc
        if not isinstance(payload, dict) or payload.get("active") is not True:
            raise LinkedInOAuthError("LinkedIn token introspection returned an inactive token.")
        if str(payload.get("client_id") or "") != self.client_id:
            raise LinkedInOAuthError("LinkedIn token introspection client mismatch.")
        return normalize_linkedin_scopes(payload.get("scope"))

    def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """Resolve OIDC identity from LinkedIn's official userinfo endpoint."""
        response = self.http_session.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise LinkedInOAuthError("LinkedIn OIDC userinfo request failed.")
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise LinkedInOAuthError("LinkedIn OIDC userinfo response is invalid.") from exc
        if not isinstance(payload, dict) or not payload.get("sub"):
            raise LinkedInOAuthError("LinkedIn OIDC identity is missing a subject.")
        return payload

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
                id_token=str(payload["id_token"]) if payload.get("id_token") else None,
                scope_field_present=bool(payload.get("scope_field_present", True)),
                raw_scope_type=str(payload.get("raw_scope_type", "str")),
                scope_source=str(payload.get("scope_source", "token_response")),
                introspection_attempted=bool(payload.get("introspection_attempted", False)),
            )
        except (OSError, InvalidToken, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LinkedInOAuthError("Stored LinkedIn OAuth tokens could not be decrypted.") from exc

    @staticmethod
    def validate_id_token(id_token: str, *, client_id: str) -> dict[str, Any]:
        """Validate required OIDC claims structurally before accepting identity."""
        try:
            header, payload, _signature = id_token.split(".")
            _ = json.loads(base64.urlsafe_b64decode(header + "=="))
            claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LinkedInOAuthError("LinkedIn OIDC ID token is malformed.") from exc
        if claims.get("iss") != "https://www.linkedin.com/oauth":
            raise LinkedInOAuthError("LinkedIn OIDC issuer is invalid.")
        if claims.get("aud") != client_id:
            raise LinkedInOAuthError("LinkedIn OIDC audience is invalid.")
        if int(claims.get("exp", 0)) <= int(time.time()) or not claims.get("sub"):
            raise LinkedInOAuthError("LinkedIn OIDC ID token is expired or missing subject.")
        return claims

    @staticmethod
    def _build_fernet(key: str) -> Fernet:
        if not key.strip():
            raise LinkedInOAuthError("LINKEDIN_TOKEN_ENCRYPTION_KEY is required.")
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise LinkedInOAuthError("LINKEDIN_TOKEN_ENCRYPTION_KEY is invalid.") from exc
