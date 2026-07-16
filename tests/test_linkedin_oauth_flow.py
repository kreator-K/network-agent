"""Focused B1 state, callback, and credential-storage tests."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from db.database import connect, initialize_database
from integrations.linkedin_oauth_callback import (
    LinkedInCredentialStore,
    complete_linkedin_callback,
    local_linkedin_status,
)
from integrations.linkedin_oauth_client import LinkedInOAuthClient, LinkedInOAuthError, LinkedInOAuthStateStore, LinkedInTokenSet


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


def test_credential_scopes_are_persisted_as_canonical_json_list(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    store = LinkedInCredentialStore(connection, KEY)
    store.save(
        LinkedInTokenSet("access", None, 3600, "w_member_social openid profile"),
        {"sub": "member-1"},
    )
    row = connection.execute("SELECT granted_scopes FROM linkedin_credentials").fetchone()
    assert row[0] == '["openid","profile","w_member_social"]'


def test_status_reads_legacy_scope_text_and_reports_connected(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    store = LinkedInCredentialStore(connection, KEY)
    store.save(LinkedInTokenSet("access", None, 3600, "openid profile w_member_social"), {"sub": "member-1"})
    connection.execute("UPDATE linkedin_credentials SET granted_scopes=?", ("openid profile w_member_social",))
    result = store.status("disabled")
    assert result["status"] == "connected"
    assert result["granted_scopes"] == ["openid", "profile", "w_member_social"]


def test_status_reports_missing_permissions_without_connecting(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    store = LinkedInCredentialStore(connection, KEY)
    store.save(LinkedInTokenSet("access", None, 3600, "openid profile w_member_social"), {"sub": "member-1"})
    connection.execute("UPDATE linkedin_credentials SET granted_scopes=?", ('["openid","profile"]',))
    result = store.status("disabled")
    assert result["status"] == "permission_missing"
    assert result["missing_scopes"] == ["w_member_social"]


def test_database_initialization_canonicalizes_legacy_scopes(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    store = LinkedInCredentialStore(connection, KEY)
    store.save(LinkedInTokenSet("access", None, 3600, "openid profile w_member_social"), {"sub": "member-1"})
    connection.execute("UPDATE linkedin_credentials SET granted_scopes=?", ("openid profile w_member_social",))
    connection.commit()
    initialize_database(tmp_path / "oauth.db")
    row = connection.execute("SELECT granted_scopes FROM linkedin_credentials").fetchone()
    assert row[0] == '["openid","profile","w_member_social"]'


def test_local_status_preserves_granted_scopes_after_restart(tmp_path: Path) -> None:
    connection = setup_db(tmp_path)
    LinkedInCredentialStore(connection, KEY).save(
        LinkedInTokenSet("access", None, 3600, "openid profile w_member_social"),
        {"sub": "member-1"},
    )
    connection.close()

    restarted = connect(tmp_path / "oauth.db")
    result = local_linkedin_status(
        restarted,
        client_id="client",
        client_secret="secret",
        redirect_uri="https://example.test/oauth/linkedin/callback",
        scopes="openid profile w_member_social",
        encryption_key=KEY,
        publish_mode="disabled",
        real_publish_enabled=False,
    )
    restarted.close()

    assert result["status"] == "connected"
    assert result["granted_scopes"] == ["openid", "profile", "w_member_social"]
    assert result["missing_scopes"] == []
    assert result["member_identity_resolved"] is True
    assert result["real_publishing_available"] is False
