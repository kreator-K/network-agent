"""Provider-neutral callback completion for the direct LinkedIn OAuth flow."""

from __future__ import annotations

import json
import sqlite3
import secrets
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


def browser_failure(reference: str) -> str:
    return f"<!doctype html><html><body><p>LinkedIn authorization could not be completed.</p><p>Reference: {escape(reference)}</p><p>Return to Telegram and run /linkedin_connect again.</p></body></html>"


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
            missing = ", ".join(sorted(set(LINKEDIN_SCOPES) - scopes))
            raise LinkedInOAuthError(f"LinkedIn authorization did not grant required scopes: {missing}.")
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


def local_linkedin_status(connection: sqlite3.Connection, *, client_id: str, client_secret: str,
                          redirect_uri: str, scopes: str, encryption_key: str,
                          publish_mode: str, real_publish_enabled: bool) -> dict[str, Any]:
    """Return local readiness without requiring OAuth or a provider request."""
    missing = [name for name, value in {
        "LINKEDIN_CLIENT_ID": client_id, "LINKEDIN_CLIENT_SECRET": client_secret,
        "LINKEDIN_REDIRECT_URI": redirect_uri, "LINKEDIN_TOKEN_ENCRYPTION_KEY": encryption_key,
    }.items() if not value.strip()]
    redirect_valid = redirect_uri.startswith("https://")
    scope_valid = set(scopes.split()) == set(LINKEDIN_SCOPES)
    key_valid = False
    if encryption_key.strip():
        try:
            Fernet(encryption_key.encode("ascii"))
            key_valid = True
        except (ValueError, UnicodeEncodeError):
            pass
    table_available: bool = False
    status: dict[str, Any]
    try:
        connection.execute("SELECT 1 FROM linkedin_credentials LIMIT 1").fetchone()
        table_available = True
        status = LinkedInCredentialStore(connection, encryption_key).status(publish_mode) if key_valid else {"status": "authorization_required", "member_identity_resolved": False, "granted_scopes": []}
    except (sqlite3.Error, LinkedInOAuthError):
        table_available = False
        status = {"status": "provider_unavailable", "member_identity_resolved": False, "granted_scopes": []}
    if missing or not redirect_valid or not scope_valid or not key_valid or not table_available:
        connection_state = "configuration_incomplete" if missing or not redirect_valid or not scope_valid or not key_valid else "provider_unavailable"
    else:
        connection_state = status["status"]
    return {
        "status": connection_state, "missing": missing, "client_id_configured": bool(client_id.strip()),
        "client_secret_configured": bool(client_secret.strip()), "redirect_uri_valid": redirect_valid,
        "scopes_allowlisted": scope_valid, "w_member_social_requested": "w_member_social" in scopes.split(),
        "token_encryption_key_valid": key_valid, "credential_table_available": table_available,
        "active_credential_available": status.get("status") == "connected",
        "member_identity_resolved": bool(status.get("member_identity_resolved")),
        "publishing_mode": publish_mode, "real_publish_enabled": real_publish_enabled,
        "real_publishing_available": False,
    }


def complete_linkedin_callback(
    params: Mapping[str, str], *, connection: sqlite3.Connection,
    oauth_client: LinkedInOAuthClient, credentials: LinkedInCredentialStore,
) -> dict[str, Any]:
    """Complete one callback without exposing provider data to the browser."""
    state = params.get("state", "")
    if params.get("error") or not state or not params.get("code"):
        raise LinkedInOAuthError("LinkedIn authorization failed or expired.")
    states = LinkedInOAuthStateStore(connection)
    state_row = states.consume(state)
    correlation_id = "LI-OAUTH-" + secrets.token_hex(6)
    try:
        if state_row["redirect_uri"] and state_row["redirect_uri"] != oauth_client.redirect_uri:
            raise LinkedInOAuthError("LinkedIn callback redirect mismatch.")
        tokens = oauth_client.exchange_code(params["code"], persist_tokens=False)
        identity = oauth_client.fetch_userinfo(tokens.access_token)
        result = credentials.save(tokens, identity)
        return {"status": "connected", "state_id": state_row["id"], **result, "browser_html": browser_result(True)}
    except Exception as exc:
        reason = "oidc_identity_invalid"
        stage = "identity_validation"
        message = str(exc).lower()
        if "token exchange" in message or "token response" in message:
            reason, stage = "token_exchange_failed", "token_exchange"
        elif "scope" in message:
            reason, stage = "required_scope_missing", "scope_validation"
        elif "encrypt" in message or "fernet" in message:
            reason, stage = "token_encryption_failed", "encryption"
        elif "identity" not in message and "userinfo" not in message:
            reason, stage = "credential_persistence_failed", "persistence"
        states.mark_failed(state_row["id"], stage=stage, reason=reason, correlation_id=correlation_id)
        raise LinkedInOAuthError(f"{reason}:{correlation_id}") from exc
