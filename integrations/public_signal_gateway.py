"""Safe public RSS and Atom feed-fetching boundary.

This gateway performs network and parsing work only. It does not persist,
normalize, score, or generate any content.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests

from config.settings import settings


class PublicSignalGatewayError(RuntimeError):
    """Base error for safe public signal fetch failures."""


class UnsafePublicSignalUrlError(PublicSignalGatewayError):
    """Raised when a URL is private, credentialed, or otherwise unsafe."""


class UnsupportedFeedContentTypeError(PublicSignalGatewayError):
    """Raised when a response is not plausibly XML feed content."""


class PublicSignalTimeoutError(PublicSignalGatewayError):
    """Raised when a feed request times out."""


class FeedResponseTooLargeError(PublicSignalGatewayError):
    """Raised when a response exceeds the configured byte cap."""


class FeedParseError(PublicSignalGatewayError):
    """Raised when RSS or Atom XML cannot be parsed."""


@dataclass(frozen=True, slots=True)
class PublicSignalSourceRequest:
    """Approved source metadata needed for a conditional feed request."""

    source_id: int
    url: str
    source_type: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class RawFeedItem:
    """Attribution-preserving feed entry before application normalization."""

    external_id: str | None
    title: str | None
    summary: str | None
    author: str | None
    published_at: str | None
    updated_at: str | None
    link: str | None
    raw_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FeedFetchResult:
    """Typed public-feed result returned without persistence side effects."""

    source_url: str
    http_status: int
    fetched_at: str
    etag: str | None
    last_modified: str | None
    feed_title: str | None
    items: list[RawFeedItem] = field(default_factory=list)
    not_modified: bool = False
    warnings: list[str] = field(default_factory=list)


def validate_public_signal_url(
    url: str,
    *,
    allow_http: bool | None = None,
    resolve_host: bool = True,
) -> str:
    """Validate a public feed URL and return its normalized request URL."""
    parsed = urlsplit(url.strip())
    allowed_schemes = {"https"}
    if settings.public_signal_allow_http if allow_http is None else allow_http:
        allowed_schemes.add("http")
    if parsed.scheme.lower() not in allowed_schemes:
        raise UnsafePublicSignalUrlError("Only approved HTTP(S) feed URLs are allowed.")
    if not parsed.hostname:
        raise UnsafePublicSignalUrlError("Feed URL must include a public hostname.")
    if parsed.username or parsed.password:
        raise UnsafePublicSignalUrlError("Feed URLs cannot include embedded credentials.")
    host = parsed.hostname.lower().rstrip(".")
    if _is_linkedin_host(host):
        raise UnsafePublicSignalUrlError("LinkedIn URLs cannot be used as signal sources.")
    _validate_host_literal(host)
    if resolve_host:
        _validate_resolved_host(host, parsed.port)
    path = parsed.path or "/"
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path).geturl()


def fetch_feed(source: PublicSignalSourceRequest) -> FeedFetchResult:
    """Fetch and parse an approved RSS or Atom source with safety limits."""
    current_url = validate_public_signal_url(source.url)
    headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified

    for redirect_count in range(settings.public_signal_max_redirects + 1):
        try:
            response = requests.get(
                current_url,
                headers=headers,
                timeout=(
                    settings.public_signal_connect_timeout_seconds,
                    settings.public_signal_read_timeout_seconds,
                ),
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout as exc:
            raise PublicSignalTimeoutError("Public feed request timed out.") from exc
        except requests.RequestException as exc:
            raise PublicSignalGatewayError("Public feed request failed.") from exc

        if response.status_code == 304:
            response.close()
            return FeedFetchResult(
                source_url=current_url,
                http_status=304,
                fetched_at=_utc_now(),
                etag=source.etag,
                last_modified=source.last_modified,
                feed_title=None,
                not_modified=True,
            )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise PublicSignalGatewayError("Feed redirect did not include a location.")
            if redirect_count >= settings.public_signal_max_redirects:
                raise PublicSignalGatewayError("Feed redirect limit exceeded.")
            current_url = validate_public_signal_url(urljoin(current_url, location))
            continue
        if response.status_code != 200:
            response.close()
            raise PublicSignalGatewayError(
                f"Public feed returned HTTP status {response.status_code}."
            )
        _validate_content_type(response.headers.get("Content-Type", ""))
        body = _read_limited_response(response)
        response.close()
        feed_title, items, warnings = _parse_feed(body, settings.public_signal_max_items_per_fetch)
        return FeedFetchResult(
            source_url=current_url,
            http_status=200,
            fetched_at=_utc_now(),
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            feed_title=feed_title,
            items=items,
            warnings=warnings,
        )
    raise PublicSignalGatewayError("Feed redirect handling failed.")


def _validate_content_type(content_type: str) -> None:
    normalized = content_type.lower().split(";", 1)[0].strip()
    allowed = {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
        "application/xhtml+xml",
    }
    if normalized and normalized not in allowed:
        raise UnsupportedFeedContentTypeError(
            f"Unsupported feed content type '{normalized}'."
        )


def _read_limited_response(response: requests.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > settings.public_signal_max_response_bytes:
            raise FeedResponseTooLargeError("Public feed exceeded the response-size limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_feed(body: bytes, max_items: int) -> tuple[str | None, list[RawFeedItem], list[str]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise FeedParseError("Public feed XML could not be parsed.") from exc
    local_name = _local_name(root.tag)
    if local_name == "rss" or root.find("channel") is not None:
        return _parse_rss(root, max_items)
    if local_name == "feed":
        return _parse_atom(root, max_items)
    raise FeedParseError("XML response was not an RSS or Atom feed.")


def _parse_rss(root: ElementTree.Element, max_items: int) -> tuple[str | None, list[RawFeedItem], list[str]]:
    channel = root.find("channel") if _local_name(root.tag) == "rss" else root
    if channel is None:
        raise FeedParseError("RSS feed did not include a channel.")
    title = _element_text(channel.find("title"))
    items: list[RawFeedItem] = []
    warnings: list[str] = []
    for entry in channel.findall("item")[:max_items]:
        guid = _element_text(entry.find("guid"))
        link = _element_text(entry.find("link"))
        published = _element_text(entry.find("pubDate"))
        summary = _element_text(entry.find("description"))
        author = _element_text(entry.find("author")) or _element_text(entry.find("creator"))
        items.append(
            RawFeedItem(
                external_id=guid,
                title=_element_text(entry.find("title")),
                summary=summary,
                author=author,
                published_at=published,
                updated_at=None,
                link=link,
                raw_metadata={"feed_format": "rss", "guid": guid},
            )
        )
    if len(channel.findall("item")) > max_items:
        warnings.append("Feed item count exceeded the configured per-fetch limit.")
    return title, items, warnings


def _parse_atom(root: ElementTree.Element, max_items: int) -> tuple[str | None, list[RawFeedItem], list[str]]:
    title = _child_text_by_local_name(root, "title")
    entries = [element for element in root if _local_name(element.tag) == "entry"]
    items: list[RawFeedItem] = []
    warnings: list[str] = []
    for entry in entries[:max_items]:
        link = _atom_link(entry)
        author_node = next((node for node in entry if _local_name(node.tag) == "author"), None)
        author = _child_text_by_local_name(author_node, "name") if author_node is not None else None
        items.append(
            RawFeedItem(
                external_id=_child_text_by_local_name(entry, "id"),
                title=_child_text_by_local_name(entry, "title"),
                summary=_child_text_by_local_name(entry, "summary")
                or _child_text_by_local_name(entry, "content"),
                author=author,
                published_at=_child_text_by_local_name(entry, "published"),
                updated_at=_child_text_by_local_name(entry, "updated"),
                link=link,
                raw_metadata={"feed_format": "atom", "id": _child_text_by_local_name(entry, "id")},
            )
        )
    if len(entries) > max_items:
        warnings.append("Feed item count exceeded the configured per-fetch limit.")
    return title, items, warnings


def _atom_link(entry: ElementTree.Element) -> str | None:
    links = [node for node in entry if _local_name(node.tag) == "link"]
    alternate = next((node for node in links if node.attrib.get("rel", "alternate") == "alternate"), None)
    target = alternate if alternate is not None else (links[0] if links else None)
    return target.attrib.get("href") if target is not None else None


def _child_text_by_local_name(element: ElementTree.Element | None, name: str) -> str | None:
    if element is None:
        return None
    child = next((node for node in element if _local_name(node.tag) == name), None)
    return _element_text(child)


def _element_text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = " ".join(element.text.strip().split())
    return value or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_linkedin_host(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _validate_host_literal(host: str) -> None:
    if host in {"localhost", "metadata.google.internal"}:
        raise UnsafePublicSignalUrlError("Local and metadata hosts are not allowed.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    _validate_public_ip(address)


def _validate_resolved_host(host: str, port: int | None) -> None:
    try:
        rows = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafePublicSignalUrlError("Feed hostname could not be resolved.") from exc
    for row in rows:
        _validate_public_ip(ipaddress.ip_address(row[4][0]))


def _validate_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise UnsafePublicSignalUrlError("Private or reserved network targets are not allowed.")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
