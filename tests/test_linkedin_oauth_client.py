"""Tests for the disabled LinkedIn OAuth foundation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.linkedin_oauth_client import (
    LINKEDIN_SCOPES,
    LinkedInOAuthClient,
    LinkedInOAuthError,
    normalize_linkedin_scopes,
)
import requests


KEY = "J7m8v5Tq8nYx3V4r8J5p6Qw7E2s1L9a0B6c4D8e2F7g="


class FakeHTTP:
    def post(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "openid profile w_member_social",
            },
        )


def make_client(tmp_path: Path) -> LinkedInOAuthClient:
    return LinkedInOAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://localhost/callback",
        encryption_key=KEY,
        token_path=tmp_path / "linkedin.enc",
        http_session=FakeHTTP(),
    )


def test_authorization_url_uses_only_allowlisted_scopes(tmp_path: Path) -> None:
    url, state = make_client(tmp_path).authorization_url(state="csrf")
    assert "scope=openid+profile+w_member_social" in url
    assert state == "csrf"
    assert all(scope in url for scope in LINKEDIN_SCOPES)


def test_exchange_encrypts_tokens_before_storage(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    tokens = client.exchange_code("code")
    assert tokens.access_token == "access"
    raw = client.token_path.read_bytes()
    assert b"access" not in raw
    assert client.load_tokens() == tokens


def test_invalid_state_or_code_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    with pytest.raises(LinkedInOAuthError):
        client.exchange_code("", state_valid=True)
    with pytest.raises(LinkedInOAuthError):
        client.exchange_code("code", state_valid=False)


def test_missing_encryption_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(LinkedInOAuthError):
        LinkedInOAuthClient(
            client_id="id", client_secret="secret", redirect_uri="uri",
            encryption_key="", token_path=tmp_path / "tokens",
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("openid profile w_member_social", {"openid", "profile", "w_member_social"}),
        ("openid+profile+w_member_social", {"openid", "profile", "w_member_social"}),
        ("openid%20profile%20w_member_social", {"openid", "profile", "w_member_social"}),
        ("openid,profile,w_member_social", {"openid", "profile", "w_member_social"}),
        ("  openid   profile\t w_member_social  ", {"openid", "profile", "w_member_social"}),
        (["openid", "profile", "w_member_social"], {"openid", "profile", "w_member_social"}),
        (("w_member_social", "profile", "openid"), {"openid", "profile", "w_member_social"}),
        (None, set()),
    ],
)
def test_scope_normalization(raw: object, expected: set[str]) -> None:
    assert normalize_linkedin_scopes(raw) == expected


class IntrospectionHTTP:
    def __init__(self, payload: dict[str, object] | None = None, *, timeout: bool = False) -> None:
        self.payload = payload or {}
        self.timeout = timeout
        self.calls: list[str] = []

    def post(self, url: str, **_kwargs: object) -> SimpleNamespace:
        self.calls.append(url)
        if len(self.calls) == 1:
            return SimpleNamespace(status_code=200, json=lambda: {"access_token": "access", "expires_in": 3600})
        if self.timeout:
            raise requests.Timeout("redacted")
        return SimpleNamespace(status_code=200, json=lambda: self.payload)


def test_missing_scope_uses_introspection(tmp_path: Path) -> None:
    http = IntrospectionHTTP({"active": True, "client_id": "client-id", "scope": "openid,profile,w_member_social"})
    oauth = make_client(tmp_path)
    oauth.http_session = http
    tokens = oauth.exchange_code("code", persist_tokens=False)
    assert normalize_linkedin_scopes(tokens.scope) == set(LINKEDIN_SCOPES)
    assert tokens.introspection_attempted is True
    assert tokens.scope_field_present is False


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"active": False, "client_id": "client-id", "scope": "openid,profile,w_member_social"}, "inactive"),
        ({"active": True, "client_id": "different", "scope": "openid,profile,w_member_social"}, "client mismatch"),
    ],
)
def test_introspection_rejects_invalid_result(tmp_path: Path, payload: dict[str, object], message: str) -> None:
    oauth = make_client(tmp_path)
    oauth.http_session = IntrospectionHTTP(payload)
    with pytest.raises(LinkedInOAuthError, match=message):
        oauth.exchange_code("code", persist_tokens=False)


def test_introspection_timeout_is_controlled(tmp_path: Path) -> None:
    oauth = make_client(tmp_path)
    oauth.http_session = IntrospectionHTTP(timeout=True)
    with pytest.raises(LinkedInOAuthError, match="timed out"):
        oauth.exchange_code("code", persist_tokens=False)


@pytest.mark.parametrize("scope", ["profile w_member_social", "openid w_member_social", "openid profile"])
def test_genuine_missing_scope_remains_missing(scope: str) -> None:
    assert set(LINKEDIN_SCOPES).difference(normalize_linkedin_scopes(scope))


def test_unexpected_scope_is_preserved_for_diagnostics() -> None:
    scopes = normalize_linkedin_scopes("w_member_social openid extra profile")
    assert scopes.difference(LINKEDIN_SCOPES) == {"extra"}
