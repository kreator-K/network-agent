"""Mocked official LinkedIn REST client tests; no network is used."""

from typing import Any

import pytest
import requests

from integrations.linkedin_api_client import (
    LinkedInApiClient,
    LinkedInApiRejectedError,
    LinkedInApiResponseError,
    LinkedInApiUncertainError,
    safe_provider_message,
)


class Response:
    def __init__(self, status: int, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class HTTP:
    def __init__(self, posts: list[Any] | None = None, puts: list[Any] | None = None, gets: list[Any] | None = None) -> None:
        self.posts = list(posts or [])
        self.puts = list(puts or [])
        self.gets = list(gets or [])
        self.post_calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.post_calls.append({"url": url, **kwargs})
        result = self.posts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def put(self, url: str, **kwargs: Any) -> Any:
        self.put_calls.append({"url": url, **kwargs})
        result = self.puts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url: str, **kwargs: Any) -> Any:
        self.get_calls.append({"url": url, **kwargs})
        result = self.gets.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def client(http: HTTP) -> LinkedInApiClient:
    return LinkedInApiClient(access_token="secret-token", api_version="202606", http_session=http)


def test_text_post_uses_required_headers_and_case_insensitive_post_id() -> None:
    http = HTTP([Response(201, headers={"X-RestLi-Id": "urn:li:share:123"})])
    result = client(http).create_post({"author": "urn:li:person:1"})
    assert result.post_id == "urn:li:share:123"
    headers = http.post_calls[0]["headers"]
    assert headers["Linkedin-Version"] == "202606"
    assert headers["X-Restli-Protocol-Version"] == "2.0.0"
    assert headers["Authorization"] == "Bearer secret-token"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_expected_4xx_is_definitive_rejection(status: int) -> None:
    with pytest.raises(LinkedInApiRejectedError):
        client(HTTP([Response(status, {"message": "rejected"})])).create_post({})


@pytest.mark.parametrize("result", [Response(429), Response(500), requests.Timeout(), requests.ConnectionError()])
def test_rate_limit_and_transport_failures_are_uncertain(result: Any) -> None:
    with pytest.raises(LinkedInApiUncertainError):
        client(HTTP([result])).create_post({})


def test_missing_post_id_is_uncertain_malformed_success() -> None:
    with pytest.raises(LinkedInApiResponseError):
        client(HTTP([Response(201)])).create_post({})


def test_image_initialization_and_upload_never_send_oauth_to_upload_host() -> None:
    http = HTTP(
        [Response(200, {"value": {"image": "urn:li:image:abc", "uploadUrl": "https://www.linkedin.com/dms-uploads/file"}})],
        [Response(201, headers={"ETag": "part-1"})],
    )
    api = client(http)
    session = api.initialize_image_upload("urn:li:person:1")
    etag = api.upload_bytes(session.upload_urls[0], b"image", content_type="image/png")
    assert session.asset_urn == "urn:li:image:abc"
    assert etag == "part-1"
    assert "Authorization" not in http.put_calls[0]["headers"]


def test_untrusted_upload_url_is_rejected() -> None:
    http = HTTP([Response(200, {"value": {"image": "urn:li:image:abc", "uploadUrl": "https://evil.example/upload"}})])
    with pytest.raises(LinkedInApiRejectedError):
        client(http).initialize_image_upload("urn:li:person:1")


def test_secret_redaction_removes_token_like_values() -> None:
    message = safe_provider_message("Authorization: Bearer token-value access_token=abc client_secret=xyz")
    assert "token-value" not in message
    assert "access_token=abc" not in message
    assert "client_secret=xyz" not in message


def test_client_does_not_retry_writes() -> None:
    http = HTTP([Response(500)])
    with pytest.raises(LinkedInApiUncertainError):
        client(http).create_post({})
    assert len(http.post_calls) == 1


def test_video_initialization_preserves_exact_byte_ranges() -> None:
    http = HTTP([Response(200, {"value": {
        "video": "urn:li:video:abc", "uploadToken": "token",
        "uploadInstructions": [
            {"uploadUrl": "https://www.linkedin.com/dms-uploads/one", "firstByte": 0, "lastByte": 3},
            {"uploadUrl": "https://www.linkedin.com/dms-uploads/two", "firstByte": 4, "lastByte": 7},
        ],
    }})])
    session = client(http).initialize_video_upload("urn:li:person:1", 8)
    assert [(part.first_byte, part.last_byte) for part in session.parts] == [(0, 3), (4, 7)]


def test_asset_processing_status_is_read_once() -> None:
    http = HTTP(gets=[Response(200, {"status": "AVAILABLE"})])
    assert client(http).get_asset_status("video", "urn:li:video:abc") == "AVAILABLE"
    assert len(http.get_calls) == 1


def test_upload_initialization_preserves_expiry() -> None:
    http = HTTP([Response(200, {"value": {
        "image": "urn:li:image:abc",
        "uploadUrl": "https://www.linkedin.com/dms-uploads/file?temporary=sensitive",
        "uploadUrlExpiresAt": 1900000000000,
    }})])
    session = client(http).initialize_image_upload("urn:li:person:1")
    assert session.upload_url_expires_at == 1900000000000


def test_api_host_and_version_are_restricted() -> None:
    with pytest.raises(ValueError):
        LinkedInApiClient(access_token="x", api_version="202606", api_base_url="https://evil.example")
    with pytest.raises(ValueError):
        LinkedInApiClient(access_token="x", api_version="latest")
