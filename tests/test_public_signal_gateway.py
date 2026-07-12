"""Tests for safe RSS and Atom feed fetching."""

import socket
from typing import Any

import pytest
import pytest_mock

from integrations import public_signal_gateway as gateway


RSS = b"""<?xml version='1.0'?><rss version='2.0'><channel><title>Example</title><item><guid>one</guid><title> First item </title><description> Summary </description><link>https://example.com/a</link><pubDate>Tue, 10 Jun 2025 10:00:00 GMT</pubDate></item></channel></rss>"""
ATOM = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><title>Example</title><entry><id>one</id><title>First atom item</title><summary>Summary</summary><link href='https://example.com/a'/><updated>2025-06-10T10:00:00Z</updated></entry></feed>"""


class FakeResponse:
    def __init__(self, status_code: int, body: bytes = RSS, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"Content-Type": "application/rss+xml"}
        self.closed = False

    def iter_content(self, chunk_size: int) -> list[bytes]:
        _ = chunk_size
        return [self._body]

    def close(self) -> None:
        self.closed = True


def _public_dns(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    _ = args, kwargs
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


def _request() -> gateway.PublicSignalSourceRequest:
    return gateway.PublicSignalSourceRequest(1, "https://example.com/feed.xml", "rss")


def test_parse_rss_and_atom() -> None:
    rss_title, rss_items, _ = gateway._parse_feed(RSS, 50)
    atom_title, atom_items, _ = gateway._parse_feed(ATOM, 50)

    assert rss_title == "Example"
    assert rss_items[0].external_id == "one"
    assert atom_title == "Example"
    assert atom_items[0].title == "First atom item"


def test_malformed_xml_fails_cleanly() -> None:
    with pytest.raises(gateway.FeedParseError):
        gateway._parse_feed(b"not xml", 50)


def test_unsafe_urls_are_rejected_without_fetching() -> None:
    for url in (
        "https://localhost/feed.xml",
        "https://127.0.0.1/feed.xml",
        "https://[::1]/feed.xml",
        "https://user:pass@example.com/feed.xml",
        "https://www.linkedin.com/feed.xml",
    ):
        with pytest.raises(gateway.UnsafePublicSignalUrlError):
            gateway.validate_public_signal_url(url, resolve_host=False)


def test_fetch_sends_conditional_headers_and_handles_not_modified(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(gateway.socket, "getaddrinfo", side_effect=_public_dns)
    request_get = mocker.patch.object(
        gateway.requests,
        "get",
        return_value=FakeResponse(304),
    )

    result = gateway.fetch_feed(
        gateway.PublicSignalSourceRequest(
            1,
            "https://example.com/feed.xml",
            "rss",
            etag='"tag"',
            last_modified="Tue, 10 Jun 2025 10:00:00 GMT",
        )
    )

    assert result.not_modified is True
    assert request_get.call_args.kwargs["headers"]["If-None-Match"] == '"tag"'
    assert request_get.call_args.kwargs["headers"]["If-Modified-Since"]


def test_fetch_rejects_unsupported_content_type(mocker: pytest_mock.MockerFixture) -> None:
    mocker.patch.object(gateway.socket, "getaddrinfo", side_effect=_public_dns)
    mocker.patch.object(
        gateway.requests,
        "get",
        return_value=FakeResponse(200, headers={"Content-Type": "text/html"}),
    )

    with pytest.raises(gateway.UnsupportedFeedContentTypeError):
        gateway.fetch_feed(_request())
