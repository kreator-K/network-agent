"""Official LinkedIn REST write client; no business decisions live here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import requests

from integrations.linkedin_publish_models import LinkedInUploadPart, LinkedInUploadSession


class LinkedInApiError(RuntimeError):
    """Base controlled provider error."""


class LinkedInApiRejectedError(LinkedInApiError):
    """LinkedIn definitively rejected a write."""


class LinkedInApiUncertainError(LinkedInApiError):
    """A write may have reached LinkedIn but no safe result was observed."""


class LinkedInApiResponseError(LinkedInApiUncertainError):
    """LinkedIn returned a malformed success response."""


@dataclass(frozen=True)
class LinkedInPostResult:
    post_id: str


_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+|(?:access[_-]?|refresh[_-]?)?token[=:]\s*|client[_-]?secret[=:]\s*)[^\s,;]+"
)
_API_HOST = "api.linkedin.com"
_UPLOAD_HOST_SUFFIXES = (".linkedin.com", ".licdn.com")


def safe_provider_message(value: object, limit: int = 1000) -> str:
    """Redact credential-like material and bound durable provider details."""
    text = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}[REDACTED]", str(value))
    return " ".join(text.split())[:limit] or "LinkedIn request failed."


class LinkedInApiClient:
    """Perform the allowlisted LinkedIn Posts and media upload operations."""

    def __init__(
        self,
        *,
        access_token: str,
        api_version: str,
        restli_protocol_version: str = "2.0.0",
        api_base_url: str = "https://api.linkedin.com",
        timeout_seconds: int = 30,
        http_session: Any | None = None,
    ) -> None:
        parsed = urlparse(api_base_url)
        if parsed.scheme != "https" or parsed.hostname != _API_HOST or parsed.path.rstrip("/"):
            raise ValueError("LinkedIn API base URL must be https://api.linkedin.com.")
        if not re.fullmatch(r"\d{6}", api_version):
            raise ValueError("LinkedIn API version must use YYYYMM format.")
        if not access_token:
            raise ValueError("An active LinkedIn access token is required.")
        self._access_token = access_token
        self.api_version = api_version
        self.restli_protocol_version = restli_protocol_version
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http = http_session or requests.Session()

    def initialize_image_upload(self, owner_urn: str) -> LinkedInUploadSession:
        response = self._api_post(
            "/rest/images?action=initializeUpload",
            {"initializeUploadRequest": {"owner": owner_urn}},
        )
        return self._parse_upload_session(response, "image", "urn:li:image:")

    def initialize_document_upload(self, owner_urn: str) -> LinkedInUploadSession:
        response = self._api_post(
            "/rest/documents?action=initializeUpload",
            {"initializeUploadRequest": {"owner": owner_urn}},
        )
        return self._parse_upload_session(response, "document", "urn:li:document:")

    def initialize_video_upload(
        self,
        owner_urn: str,
        file_size_bytes: int,
        *,
        upload_thumbnail: bool = False,
        upload_captions: bool = False,
    ) -> LinkedInUploadSession:
        response = self._api_post(
            "/rest/videos?action=initializeUpload",
            {
                "initializeUploadRequest": {
                    "owner": owner_urn,
                    "fileSizeBytes": file_size_bytes,
                    "uploadThumbnail": upload_thumbnail,
                    "uploadCaptions": upload_captions,
                }
            },
        )
        return self._parse_upload_session(response, "video", "urn:li:video:")

    def upload_bytes(
        self,
        upload_url: str,
        content: bytes,
        *,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> str | None:
        self._validate_upload_url(upload_url)
        headers = {"Content-Type": content_type, **(extra_headers or {})}
        try:
            response = self.http.put(
                upload_url,
                data=content,
                headers=headers,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise LinkedInApiUncertainError("LinkedIn media upload result is uncertain.") from exc
        if response.status_code in {200, 201, 202}:
            return _header(response.headers, "etag")
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise LinkedInApiUncertainError(
                safe_provider_message(f"LinkedIn media upload returned HTTP {response.status_code}.")
            )
        raise LinkedInApiRejectedError(
            safe_provider_message(f"LinkedIn media upload was rejected with HTTP {response.status_code}: {_response_detail(response)}")
        )

    def finalize_video_upload(self, video_urn: str, upload_token: str, etags: list[str]) -> None:
        response = self._api_post(
            "/rest/videos?action=finalizeUpload",
            {"finalizeUploadRequest": {"video": video_urn, "uploadToken": upload_token, "uploadedPartIds": etags}},
        )
        if response.status_code not in {200, 201}:
            self._raise_for_response(response, operation="video finalization")

    def get_asset_status(self, asset_kind: str, asset_urn: str) -> str:
        """Read one provider processing state without polling or retrying."""
        prefixes = {"video": "urn:li:video:", "document": "urn:li:document:"}
        if asset_kind not in prefixes or not asset_urn.startswith(prefixes[asset_kind]):
            raise ValueError("Unsupported LinkedIn asset status request.")
        try:
            response = self.http.get(
                f"{self.api_base_url}/rest/{asset_kind}s/{quote(asset_urn, safe='')}",
                headers=self._headers(), timeout=self.timeout_seconds, allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise LinkedInApiUncertainError("LinkedIn asset processing status is uncertain.") from exc
        if response.status_code != 200:
            self._raise_for_response(response, operation=f"{asset_kind} status check")
        try:
            status = response.json()["status"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LinkedInApiResponseError("LinkedIn returned malformed asset processing status.") from exc
        if not isinstance(status, str) or not status:
            raise LinkedInApiResponseError("LinkedIn returned malformed asset processing status.")
        return status

    def create_post(self, payload: dict[str, Any]) -> LinkedInPostResult:
        response = self._api_post("/rest/posts", payload)
        if response.status_code != 201:
            self._raise_for_response(response, operation="post publication")
        post_id = _header(response.headers, "x-restli-id")
        if not post_id or not post_id.startswith("urn:li:"):
            raise LinkedInApiResponseError("LinkedIn returned HTTP 201 without a usable post ID.")
        return LinkedInPostResult(post_id=post_id)

    def _api_post(self, path: str, payload: dict[str, Any]) -> Any:
        if not (path.startswith("/rest/posts") or path.startswith("/rest/images") or path.startswith("/rest/videos") or path.startswith("/rest/documents")):
            raise ValueError("Unsupported LinkedIn endpoint.")
        try:
            return self.http.post(
                self.api_base_url + path,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise LinkedInApiUncertainError("LinkedIn write result is uncertain.") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Linkedin-Version": self.api_version,
            "X-Restli-Protocol-Version": self.restli_protocol_version,
        }

    def _parse_upload_session(self, response: Any, asset_field: str, urn_prefix: str) -> LinkedInUploadSession:
        if response.status_code not in {200, 201}:
            self._raise_for_response(response, operation=f"{asset_field} upload initialization")
        try:
            payload = response.json()
            value = payload["value"]
            asset_urn = value[asset_field]
            instructions = value.get("uploadInstructions")
            urls = [item["uploadUrl"] for item in instructions] if instructions else [value["uploadUrl"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise LinkedInApiResponseError(f"LinkedIn returned malformed {asset_field} upload instructions.") from exc
        if not isinstance(asset_urn, str) or not asset_urn.startswith(urn_prefix):
            raise LinkedInApiResponseError(f"LinkedIn returned an invalid {asset_field} URN.")
        if not all(isinstance(url, str) for url in urls):
            raise LinkedInApiResponseError("LinkedIn returned an invalid upload URL.")
        for url in urls:
            self._validate_upload_url(url)
        parts: list[LinkedInUploadPart] = []
        if instructions:
            try:
                parts = [
                    LinkedInUploadPart(
                        upload_url=item["uploadUrl"],
                        first_byte=int(item["firstByte"]),
                        last_byte=int(item["lastByte"]),
                    )
                    for item in instructions
                ]
            except (KeyError, TypeError, ValueError) as exc:
                raise LinkedInApiResponseError("LinkedIn returned malformed multipart byte ranges.") from exc
        expires = value.get("uploadUrlExpiresAt", value.get("uploadUrlsExpireAt"))
        thumbnail_url = value.get("thumbnailUploadUrl")
        captions_url = value.get("captionsUploadUrl")
        for optional_url in (thumbnail_url, captions_url):
            if optional_url is not None:
                if not isinstance(optional_url, str):
                    raise LinkedInApiResponseError("LinkedIn returned an invalid auxiliary upload URL.")
                self._validate_upload_url(optional_url)
        return LinkedInUploadSession(
            asset_urn=asset_urn,
            upload_urls=urls,
            parts=parts,
            upload_url_expires_at=expires if isinstance(expires, int) else None,
            upload_token=value.get("uploadToken") if isinstance(value.get("uploadToken"), str) else None,
            thumbnail_upload_url=thumbnail_url,
            captions_upload_url=captions_url,
        )

    @staticmethod
    def _validate_upload_url(upload_url: str) -> None:
        parsed = urlparse(upload_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(host == suffix[1:] or host.endswith(suffix) for suffix in _UPLOAD_HOST_SUFFIXES):
            raise LinkedInApiRejectedError("LinkedIn returned an untrusted media upload destination.")

    @staticmethod
    def _raise_for_response(response: Any, *, operation: str) -> None:
        detail = safe_provider_message(_response_detail(response))
        message = f"LinkedIn {operation} returned HTTP {response.status_code}: {detail}"
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise LinkedInApiUncertainError(message)
        raise LinkedInApiRejectedError(message)


def _header(headers: Any, name: str) -> str | None:
    target = name.casefold()
    for key, value in dict(headers).items():
        if str(key).casefold() == target:
            return str(value)
    return None


def _response_detail(response: Any) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error_description") or "provider rejection")
    except (TypeError, ValueError):
        pass
    return "provider rejection"
