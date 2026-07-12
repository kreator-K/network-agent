"""Tests for the disabled LinkedIn OAuth foundation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.linkedin_oauth_client import (
    LINKEDIN_SCOPES,
    LinkedInOAuthClient,
    LinkedInOAuthError,
)


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
