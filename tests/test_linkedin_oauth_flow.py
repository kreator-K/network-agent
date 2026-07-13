"""Focused B1 state, callback, and credential-storage tests."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from db.database import connect, initialize_database
from integrations.linkedin_oauth_callback import LinkedInCredentialStore, complete_linkedin_callback
from integrations.linkedin_oauth_client import LinkedInOAuthClient, LinkedInOAuthError, LinkedInOAuthStateStore


KEY = Fernet.generate_key().decode()


class FakeHTTP:
    def post(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status_code=200, json=lambda: {"access_token": "secret-access", "expires_in": 3600, "scope": "openid profile w_member_social"})

    def get(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status_code=200, json=lambda: {"sub": "member-1", "name": "Test Member"})


def setup_db(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "oauth.db"
    initialize_database(path)
    return connect(path)


def client(tmp_path: Path) -> LinkedInOAuthClient:
    return LinkedInOAuthClient(client_id="id", client_secret="secret", redirect_uri="https://example.test/oauth/linkedin/callback", encryption_key=KEY, token_path=tmp_path / "tokens", http_session=FakeHTTP())


def test_state_is_hashed_expiring_and_single_use(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    store = LinkedInOAuthStateStore(connection)
    request = store.create(telegram_user_id="u", telegram_chat_id="c", scopes="openid profile w_member_social", redirect_uri="https://example.test/oauth/linkedin/callback", ttl_seconds=600)
    assert request.state not in connection.execute("SELECT state_hash FROM linkedin_oauth_states").fetchone()[0]
    store.consume(request.state)
    with pytest.raises(LinkedInOAuthError, match="consumed_state"):
        store.consume(request.state)


def test_callback_encrypts_tokens_and_resolves_identity(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    oauth = client(tmp_path)
    state = LinkedInOAuthStateStore(connection).create(telegram_user_id="u", telegram_chat_id="c", scopes="openid profile w_member_social", redirect_uri=oauth.redirect_uri, ttl_seconds=600)
    result = complete_linkedin_callback({"state": state.state, "code": "code"}, connection=connection, oauth_client=oauth, credentials=LinkedInCredentialStore(connection, KEY))
    assert result["status"] == "connected"
    row = connection.execute("SELECT encrypted_access_token, oidc_subject FROM linkedin_credentials").fetchone()
    assert b"secret-access" not in row[0]
    assert row[1] == "member-1"


def test_callback_browser_failure_is_generic(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    with pytest.raises(LinkedInOAuthError):
        complete_linkedin_callback({"error": "access_denied", "state": "raw"}, connection=connection, oauth_client=client(tmp_path), credentials=LinkedInCredentialStore(connection, KEY))
