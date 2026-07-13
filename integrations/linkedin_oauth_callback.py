"""Provider-neutral callback completion for the direct LinkedIn OAuth flow."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any, Mapping

from cryptography.fernet import Fernet

from integrations.linkedin_oauth_client import (
    LINKEDIN_SCOPES,
    LinkedInOAuthClient,
    LinkedInOAuthError,
    LinkedInOAuthStateStore,
    LinkedInTokenSet,
)


def browser_result(success: bool) -> str:
    message = (
        "LinkedIn authorization completed. You may return to Telegram."
        if success else "LinkedIn authorization failed or expired. Nothing was published."
    )
    return f"<!doctype html><html><body><p>{escape(message)}</p></body></html>"


class LinkedInCredentialStore:
    """Encrypt and atomically persist the minimum LinkedIn credential data."""

    def __init__(self, connection: sqlite3.Connection, encryption_key: str) -> None:
        try:
            self.fernet = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise LinkedInOAuthError("LinkedIn token encryption is unavailable.") from exc
        self.connection = connection

    def save(self, tokens: LinkedInTokenSet, identity: Mapping[str, Any]) -> dict[str, Any]:
        subject = str(identity.get("sub") or "").strip()
        if not subject:
            raise LinkedInOAuthError("LinkedIn identity could not be validated.")
        scopes = set(tokens.scope.split())
        if set(LINKEDIN_SCOPES) - scopes:
            raise LinkedInOAuthError("LinkedIn authorization did not grant required scopes.")
        now = datetime.now(UTC)
        expiry = (now + timedelta(seconds=tokens.expires_in)).isoformat() if tokens.expires_in else None
        access = self.fernet.encrypt(tokens.access_token.encode("utf-8"))
        refresh = self.fernet.encrypt(tokens.refresh_token.encode("utf-8")) if tokens.refresh_token else None
        metadata = json.dumps({"authorized_via": "linkedin_oidc"}, sort_keys=True)
        with self.connection:
            self.connection.execute("UPDATE linkedin_credentials SET status='revoked', revoked_at=? WHERE status='active'", (now.isoformat(),))
            self.connection.execute(
                """INSERT INTO linkedin_credentials
                (encrypted_access_token, encrypted_refresh_token, oidc_subject,
                 granted_scopes, authorized_at, access_token_expires_at, status,
                 metadata_json, member_display_name)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (access, refresh, subject, " ".join(sorted(scopes)), now.isoformat(), expiry,
                 metadata, str(identity.get("name")) if identity.get("name") else None),
            )
        return {"status": "connected", "oidc_subject": subject, "scopes": sorted(scopes), "expires_at": expiry}

    def status(self, publish_mode: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM linkedin_credentials ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return {"status": "authorization_required", "required_scopes": list(LINKEDIN_SCOPES), "publishing_mode": publish_mode, "real_publishing_available": False}
        expiry = row["access_token_expires_at"]
        expired = bool(expiry and expiry <= datetime.now(UTC).isoformat())
        state = "token_expired" if expired else row["status"]
        if row["status"] == "active" and not expired and set(LINKEDIN_SCOPES).issubset(set(row["granted_scopes"].split())):
            state = "connected"
        return {"status": state, "required_scopes": list(LINKEDIN_SCOPES), "granted_scopes": row["granted_scopes"].split(), "member_identity_resolved": bool(row["oidc_subject"]), "publishing_mode": publish_mode, "real_publishing_available": False, "token_expires_at": expiry}

    def disconnect(self) -> None:
        with self.connection:
            self.connection.execute("UPDATE linkedin_credentials SET status='revoked', revoked_at=? WHERE status='active'", (datetime.now(UTC).isoformat(),))


def complete_linkedin_callback(
    params: Mapping[str, str], *, connection: sqlite3.Connection,
    oauth_client: LinkedInOAuthClient, credentials: LinkedInCredentialStore,
) -> dict[str, Any]:
    """Complete one callback without exposing provider data to the browser."""
    state = params.get("state", "")
    if params.get("error") or not state or not params.get("code"):
        raise LinkedInOAuthError("LinkedIn authorization failed or expired.")
    state_row = LinkedInOAuthStateStore(connection).consume(state)
    if state_row["redirect_uri"] and state_row["redirect_uri"] != oauth_client.redirect_uri:
        raise LinkedInOAuthError("LinkedIn callback redirect mismatch.")
    tokens = oauth_client.exchange_code(params["code"], persist_tokens=False)
    identity = oauth_client.fetch_userinfo(tokens.access_token)
    result = credentials.save(tokens, identity)
    return {"status": "connected", "state_id": state_row["id"], **result, "browser_html": browser_result(True)}
