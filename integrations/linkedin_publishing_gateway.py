"""Approval-first LinkedIn publication workflow and durable request state."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import mimetypes
import re
import socket
import sqlite3
import struct
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from config.settings import settings
from db.database import connect
from integrations.linkedin_api_client import (
    LinkedInApiClient,
    LinkedInApiError,
    LinkedInApiRejectedError,
    LinkedInApiUncertainError,
    safe_provider_message,
)
from integrations.linkedin_oauth_callback import LinkedInCredentialStore
from integrations.linkedin_publish_models import (
    ArticlePublishPayload,
    DocumentPublishPayload,
    LinkedInMediaAsset,
    MultiImagePublishPayload,
    PollPublishPayload,
    VideoPublishPayload,
)
from integrations.supabase_storage import SupabaseStorageError, read_asset_bytes


DatabaseRef = sqlite3.Connection | str | Path
ApiClientFactory = Callable[[str], Any]
FINAL_OR_UNCERTAIN = {"published_linkedin", "published_mock", "publish_uncertain", "upload_uncertain", "image_upload_uncertain", "processing_unknown"}
logger = logging.getLogger(__name__)


class LinkedInPublishingError(RuntimeError):
    """Controlled publication workflow error."""


class LinkedInProcessingUnknownError(LinkedInApiUncertainError):
    """An uploaded provider asset is not yet safely publishable."""


class LinkedInPublishingGateway:
    """Freeze, confirm, and audit one approved LinkedIn publication request."""

    def __init__(self, api_client_factory: ApiClientFactory | None = None) -> None:
        self._api_client_factory = api_client_factory or self._default_api_client

    def prepare_publish(self, post_id: int, database: DatabaseRef) -> dict[str, Any]:
        """Freeze a package without contacting LinkedIn or uploading assets."""
        self._validate_configuration(for_real=False)
        connection, close = _coerce(database)
        try:
            post = connection.execute("SELECT * FROM content_posts WHERE id=?", (post_id,)).fetchone()
            if post is None:
                raise LinkedInPublishingError(f"Content package id {post_id} does not exist.")
            self._validate_package(post)
            credential = LinkedInCredentialStore(
                connection, settings.linkedin_token_encryption_key
            ).active_credential()
            frozen = self._freeze_package(post, credential["author_urn"])
            payload_json = _canonical_json(frozen["payload"])
            payload_hash = _sha256(payload_json.encode())
            image_hashes = ":".join(asset["sha256"] for asset in frozen["assets"])
            key_material = ":".join(
                [str(post_id), str(post["package_version"]), frozen["format"], payload_hash, image_hashes, credential["author_urn"]]
            )
            idempotency_key = "linkedin:" + _sha256(key_material.encode())
            existing = connection.execute(
                "SELECT * FROM linkedin_publish_requests WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                return self._request_result(existing, reused=True)
            now = datetime.now(UTC)
            expires_at = now + timedelta(seconds=settings.linkedin_publish_request_ttl_seconds)
            cursor = connection.execute(
                """INSERT INTO linkedin_publish_requests (
                    content_post_id, package_version, publish_format, status,
                    payload_json, payload_hash, asset_manifest_json, idempotency_key,
                    credential_id, author_urn, visibility, api_version, expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'awaiting_confirmation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post_id, post["package_version"], frozen["format"], payload_json,
                    payload_hash, _canonical_json(frozen["assets"]), idempotency_key,
                    credential["credential_id"], credential["author_urn"],
                    frozen["payload"]["visibility"], settings.linkedin_api_version,
                    expires_at.isoformat(), now.isoformat(), now.isoformat(),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM linkedin_publish_requests WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            self._record_event(connection, int(row["id"]), "preview_created", "preview", {
                "package_id": post_id, "package_version": post["package_version"],
                "format": frozen["format"], "payload_fingerprint": payload_hash[:12],
                "asset_fingerprints": [asset["sha256"][:12] for asset in frozen["assets"]],
            })
            connection.commit()
            logger.info(
                "linkedin_publish_event request_id=%s package_id=%s version=%s format=%s stage=preview event=created fingerprint=%s",
                row["id"], post_id, post["package_version"], frozen["format"], payload_hash[:12],
            )
            return self._request_result(row, reused=False)
        finally:
            if close:
                connection.close()

    def confirm_publish(self, request_id: int, database: DatabaseRef) -> dict[str, Any]:
        """Claim a frozen request once and execute its configured mode."""
        connection, close = _coerce(database)
        try:
            request = self._load_request(connection, request_id)
            if request["status"] in FINAL_OR_UNCERTAIN or request["status"] != "awaiting_confirmation":
                raise LinkedInPublishingError(f"Publish request {request_id} cannot be confirmed from status {request['status']}.")
            if request["expires_at"] <= datetime.now(UTC).isoformat():
                self._set_state(connection, request_id, "expired", "request_expired", "Publish confirmation expired.")
                raise LinkedInPublishingError("Publish confirmation expired.")
            attempted = connection.execute(
                """UPDATE linkedin_publish_requests
                   SET confirmation_attempts=confirmation_attempts+1,
                       last_confirmation_attempt_at=?, updated_at=?
                   WHERE id=? AND status='awaiting_confirmation'
                     AND confirmation_attempts < ?""",
                (_now(), _now(), request_id, settings.linkedin_max_confirmation_attempts),
            ).rowcount
            connection.commit()
            if attempted != 1:
                raise LinkedInPublishingError("Publish confirmation attempt limit reached or request already claimed.")
            request = self._load_request(connection, request_id)
            self._record_event(connection, request_id, "confirmation_attempted", "confirmation", {"attempt": request["confirmation_attempts"]})
            connection.commit()
            post = connection.execute("SELECT * FROM content_posts WHERE id=?", (request["content_post_id"],)).fetchone()
            if post is None or post["status"] != "approved_for_later_posting" or post["package_version"] != request["package_version"]:
                raise LinkedInPublishingError("The approved package changed after preview creation.")
            credential = LinkedInCredentialStore(connection, settings.linkedin_token_encryption_key).active_credential()
            if credential["credential_id"] != request["credential_id"] or credential["author_urn"] != request["author_urn"]:
                raise LinkedInPublishingError("The authenticated LinkedIn member changed after preview creation.")
            frozen = self._freeze_package(post, credential["author_urn"])
            payload_json = _canonical_json(frozen["payload"])
            if _sha256(payload_json.encode()) != request["payload_hash"]:
                raise LinkedInPublishingError("Frozen LinkedIn payload hash no longer matches.")
            if _canonical_json(frozen["assets"]) != request["asset_manifest_json"]:
                raise LinkedInPublishingError("A frozen publication asset changed after preview creation.")
            mode = settings.linkedin_publish_mode.strip().lower()
            if mode == "disabled":
                return {"status": "disabled", "published": False, "message": "LinkedIn publishing is disabled. Nothing was published."}
            if mode == "real" and not settings.linkedin_real_publish_enabled:
                return {"status": "kill_switch_disabled", "published": False, "message": "Real LinkedIn publishing is disabled. Nothing was published."}
            if mode not in {"mock", "real"}:
                raise LinkedInPublishingError("Unsupported LinkedIn publishing mode.")
            claimed = connection.execute(
                """UPDATE linkedin_publish_requests
                   SET status='publishing_in_progress', confirmed_at=?, updated_at=?
                   WHERE id=? AND status='awaiting_confirmation'""",
                (_now(), _now(), request_id),
            ).rowcount
            connection.commit()
            if claimed != 1:
                raise LinkedInPublishingError("Publish confirmation was already consumed.")
            self._record_event(connection, request_id, "request_claimed", "confirmation", {"format": request["publish_format"]})
            connection.commit()
            logger.info(
                "linkedin_publish_event request_id=%s package_id=%s version=%s format=%s stage=confirmation event=claimed fingerprint=%s",
                request_id, request["content_post_id"], request["package_version"], request["publish_format"], request["payload_hash"][:12],
            )
            if mode == "mock":
                post_id = "mock:" + request["payload_hash"][:20]
                self._complete(connection, request_id, "published_mock", post_id, [])
                return {"status": "published_mock", "published": False, "provider_post_id": post_id, "message": "Mock publication recorded. Nothing was posted to LinkedIn."}
            self._validate_configuration(for_real=True)
            client = self._api_client_factory(credential["access_token"])
            return self._execute_real(connection, request, frozen, client)
        finally:
            if close:
                connection.close()

    def cancel_publish(self, request_id: int, database: DatabaseRef) -> dict[str, Any]:
        connection, close = _coerce(database)
        try:
            updated = connection.execute(
                "UPDATE linkedin_publish_requests SET status='cancelled', updated_at=? WHERE id=? AND status='awaiting_confirmation'",
                (_now(), request_id),
            ).rowcount
            connection.commit()
            if updated != 1:
                raise LinkedInPublishingError("Only an awaiting confirmation can be cancelled.")
            return self.get_request(request_id, connection)
        finally:
            if close:
                connection.close()

    def get_request(self, request_id: int, database: DatabaseRef) -> dict[str, Any]:
        connection, close = _coerce(database)
        try:
            return self._request_result(self._load_request(connection, request_id))
        finally:
            if close:
                connection.close()

    def history(self, database: DatabaseRef, limit: int = 20) -> list[dict[str, Any]]:
        connection, close = _coerce(database)
        try:
            rows = connection.execute(
                """SELECT requests.*, resolutions.decision AS resolution_decision,
                          resolutions.provider_post_id AS resolution_provider_post_id,
                          resolutions.resolved_at
                   FROM linkedin_publish_requests AS requests
                   LEFT JOIN linkedin_publish_resolutions AS resolutions ON resolutions.request_id=requests.id
                   ORDER BY requests.id DESC LIMIT ?""", (limit,)
            ).fetchall()
            return [self._request_result(row) for row in rows]
        finally:
            if close:
                connection.close()

    def resolve_uncertain(self, request_id: int, posted: bool, database: DatabaseRef, provider_post_id: str | None = None, note: str | None = None) -> dict[str, Any]:
        connection, close = _coerce(database)
        try:
            request = self._load_request(connection, request_id)
            if request["status"] not in {"publish_uncertain", "upload_uncertain", "image_upload_uncertain", "processing_unknown"}:
                raise LinkedInPublishingError("Only an uncertain request can be manually resolved.")
            if provider_post_id is not None and not provider_post_id.startswith("urn:li:"):
                raise LinkedInPublishingError("Manual provider post ID must be a LinkedIn URN.")
            try:
                connection.execute(
                    """INSERT INTO linkedin_publish_resolutions
                       (request_id, decision, provider_post_id, note, resolved_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (request_id, "posted" if posted else "not_posted", provider_post_id, safe_provider_message(note) if note else None, _now()),
                )
                self._record_event(connection, request_id, "manual_resolution", "recovery", {"decision": "posted" if posted else "not_posted", "provider_id_supplied": provider_post_id is not None})
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise LinkedInPublishingError("This uncertain request was already resolved.") from exc
            return self.get_request(request_id, connection)
        finally:
            if close:
                connection.close()

    def reconcile_stale_in_progress(self, database: DatabaseRef) -> int:
        """Mark interrupted writes uncertain without issuing provider requests."""
        connection, close = _coerce(database)
        try:
            states = (
                "publishing_in_progress", "image_upload_initializing", "image_upload_initialized",
                "image_upload_in_progress", "image_uploaded", "upload_initializing",
                "upload_in_progress", "upload_processing", "assets_uploaded",
            )
            placeholders = ",".join("?" for _ in states)
            stale_rows = connection.execute(
                f"SELECT id FROM linkedin_publish_requests WHERE status IN ({placeholders})",
                states,
            ).fetchall()
            updated = connection.execute(
                f"UPDATE linkedin_publish_requests SET status='publish_uncertain', safe_error_code='interrupted_write', safe_error_summary='A prior provider write was interrupted; inspect LinkedIn manually.', updated_at=? WHERE status IN ({placeholders})",
                (_now(), *states),
            ).rowcount
            for row in stale_rows:
                self._record_event(connection, int(row["id"]), "startup_reconciled", "reconciliation", {"result": "publish_uncertain"})
            connection.commit()
            if updated:
                logger.warning("linkedin_publish_reconciliation count=%s result=publish_uncertain", updated)
            return updated
        finally:
            if close:
                connection.close()

    def diagnostics(self, database: DatabaseRef) -> dict[str, Any]:
        """Return local read-only publishing health without provider calls."""
        connection, close = _coerce(database)
        try:
            counts = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM linkedin_publish_requests GROUP BY status"
                ).fetchall()
            }
            cutoff = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
            stale = connection.execute(
                """SELECT COUNT(*) FROM linkedin_publish_requests
                   WHERE status IN ('publishing_in_progress','image_upload_initializing',
                     'image_upload_in_progress','upload_initializing','upload_in_progress',
                     'upload_processing','assets_uploaded') AND updated_at < ?""",
                (cutoff,),
            ).fetchone()[0]
            failures = [
                {"request_id": row["id"], "status": row["status"], "code": row["safe_error_code"], "summary": row["safe_error_summary"]}
                for row in connection.execute(
                    """SELECT id, status, safe_error_code, safe_error_summary
                       FROM linkedin_publish_requests WHERE safe_error_code IS NOT NULL
                       ORDER BY id DESC LIMIT 5"""
                ).fetchall()
            ]
            reconciliation = connection.execute(
                """SELECT COUNT(*) FROM linkedin_publish_events
                   WHERE event_type='startup_reconciled'"""
            ).fetchone()[0]
            return {
                "mode": settings.linkedin_publish_mode,
                "real_publish_enabled": settings.linkedin_real_publish_enabled,
                "pending": counts.get("awaiting_confirmation", 0),
                "in_progress": sum(counts.get(state, 0) for state in ("publishing_in_progress", "image_upload_initializing", "image_upload_in_progress", "upload_initializing", "upload_in_progress", "upload_processing", "assets_uploaded")),
                "uncertain": sum(counts.get(state, 0) for state in ("publish_uncertain", "image_upload_uncertain", "upload_uncertain", "processing_unknown")),
                "stale": int(stale),
                "recent_safe_failures": failures,
                "startup_reconciled_count": int(reconciliation),
            }
        finally:
            if close:
                connection.close()

    def _execute_real(self, connection: sqlite3.Connection, request: sqlite3.Row, frozen: dict[str, Any], client: LinkedInApiClient) -> dict[str, Any]:
        request_id = int(request["id"])
        asset_urns: list[str] = []
        stage = "post"
        try:
            provider_payload = self._base_provider_payload(frozen["payload"])
            publish_format = request["publish_format"]
            if publish_format == "single_image":
                stage = "image_upload"
                asset_urns = self._upload_images(connection, request_id, frozen["assets"], client, request["author_urn"])
                provider_payload["content"] = {"media": {"id": asset_urns[0], "altText": frozen["assets"][0]["alt_text"]}}
            elif publish_format == "multi_image":
                stage = "upload"
                asset_urns = self._upload_images(connection, request_id, frozen["assets"], client, request["author_urn"])
                provider_payload["content"] = {"multiImage": {"images": [{"id": urn, "altText": asset["alt_text"]} for urn, asset in zip(asset_urns, frozen["assets"], strict=True)]}}
            elif publish_format == "document":
                stage = "upload"
                asset_urns = self._upload_document(connection, request_id, frozen["assets"][0], client, request["author_urn"])
                provider_payload["content"] = {"media": {"id": asset_urns[0], "title": frozen["payload"]["title"]}}
            elif publish_format == "video":
                stage = "upload"
                asset_urns = self._upload_video(connection, request_id, frozen["assets"], client, request["author_urn"])
                primary = next(asset for asset in frozen["assets"] if asset.get("role") == "primary")
                provider_payload["content"] = {"media": {"id": asset_urns[0], "title": primary.get("title") or "Video"}}
            elif publish_format == "article":
                provider_payload["content"] = {"article": {"source": frozen["payload"]["article_url"], "title": frozen["payload"]["title"], "description": frozen["payload"]["description"]}}
            elif publish_format == "poll":
                provider_payload["content"] = {"poll": {"question": frozen["payload"]["question"], "options": [{"text": option} for option in frozen["payload"]["options"]], "settings": {"duration": frozen["payload"]["duration"]}}}
            stage = "post"
            result = client.create_post(provider_payload)
            self._complete(connection, request_id, "published_linkedin", result.post_id, asset_urns)
            return {"status": "published_linkedin", "published": True, "provider_post_id": result.post_id, "asset_urns": asset_urns}
        except LinkedInApiRejectedError as exc:
            status = "image_upload_failed" if stage == "image_upload" else "upload_failed" if stage == "upload" else "publish_failed"
            self._set_state(connection, request_id, status, "provider_rejected", safe_provider_message(exc))
            raise LinkedInPublishingError("LinkedIn rejected the publication request. Nothing was marked published.") from exc
        except LinkedInProcessingUnknownError as exc:
            self._set_state(connection, request_id, _processing_unknown_status(connection), "processing_unknown", safe_provider_message(exc))
            raise LinkedInPublishingError("LinkedIn media processing is unresolved. Inspect LinkedIn manually before resolving it.") from exc
        except LinkedInApiUncertainError as exc:
            status = "image_upload_uncertain" if stage == "image_upload" else "upload_uncertain" if stage == "upload" else "publish_uncertain"
            self._set_state(connection, request_id, status, "provider_uncertain", safe_provider_message(exc))
            raise LinkedInPublishingError("LinkedIn publication result is uncertain. Inspect LinkedIn manually before resolving it.") from exc
        except LinkedInApiError as exc:
            self._set_state(connection, request_id, "publish_failed", "provider_error", safe_provider_message(exc))
            raise LinkedInPublishingError("LinkedIn publication failed.") from exc

    def _upload_images(self, connection: sqlite3.Connection, request_id: int, assets: list[dict[str, Any]], client: LinkedInApiClient, owner: str) -> list[str]:
        urns: list[str] = []
        for asset in assets:
            self._set_state(connection, request_id, "image_upload_initializing")
            session = client.initialize_image_upload(owner)
            _validate_upload_not_expired(session.upload_url_expires_at)
            self._set_state(connection, request_id, "image_upload_in_progress")
            client.upload_bytes(session.upload_urls[0], _read_asset(asset["path"]), content_type=asset["mime_type"])
            urns.append(session.asset_urn)
        self._store_asset_urns(connection, request_id, urns, "image_uploaded")
        return urns

    def _upload_document(self, connection: sqlite3.Connection, request_id: int, asset: dict[str, Any], client: LinkedInApiClient, owner: str) -> list[str]:
        self._set_state(connection, request_id, "upload_initializing")
        session = client.initialize_document_upload(owner)
        _validate_upload_not_expired(session.upload_url_expires_at)
        self._set_state(connection, request_id, "upload_in_progress")
        client.upload_bytes(session.upload_urls[0], _read_asset(asset["path"]), content_type=asset["mime_type"])
        self._set_state(connection, request_id, "upload_processing")
        status = client.get_asset_status("document", session.asset_urn)
        if status != "AVAILABLE":
            raise LinkedInProcessingUnknownError(f"LinkedIn document processing status is {status}.")
        self._store_asset_urns(connection, request_id, [session.asset_urn], "assets_uploaded")
        return [session.asset_urn]

    def _upload_video(self, connection: sqlite3.Connection, request_id: int, assets: list[dict[str, Any]], client: LinkedInApiClient, owner: str) -> list[str]:
        primary = next((asset for asset in assets if asset.get("role") == "primary"), None)
        thumbnail = next((asset for asset in assets if asset.get("role") == "thumbnail"), None)
        captions = next((asset for asset in assets if asset.get("role") == "captions"), None)
        if primary is None:
            raise LinkedInApiRejectedError("Approved video package has no primary media.")
        self._set_state(connection, request_id, "upload_initializing")
        session = client.initialize_video_upload(
            owner, primary["size_bytes"],
            upload_thumbnail=thumbnail is not None,
            upload_captions=captions is not None,
        )
        _validate_upload_not_expired(session.upload_url_expires_at)
        data = _read_asset(primary["path"])
        self._set_state(connection, request_id, "upload_in_progress")
        if session.parts:
            if session.parts[0].first_byte != 0 or session.parts[-1].last_byte != len(data) - 1:
                raise LinkedInApiUncertainError("LinkedIn multipart instructions do not cover the frozen video.")
            for previous, current in zip(session.parts, session.parts[1:]):
                if previous.last_byte + 1 != current.first_byte:
                    raise LinkedInApiUncertainError("LinkedIn multipart instructions contain a gap or overlap.")
            etags = [
                client.upload_bytes(
                    part.upload_url, data[part.first_byte:part.last_byte + 1],
                    content_type=primary["mime_type"],
                    extra_headers={"Content-Range": f"bytes {part.first_byte}-{part.last_byte}/{len(data)}"},
                ) or ""
                for part in session.parts
            ]
        elif len(session.upload_urls) == 1:
            etags = [client.upload_bytes(session.upload_urls[0], data, content_type=primary["mime_type"]) or ""]
        else:
            raise LinkedInApiUncertainError("LinkedIn video upload instructions did not include byte ranges.")
        if thumbnail is not None:
            if not session.thumbnail_upload_url:
                raise LinkedInApiUncertainError("LinkedIn omitted the requested thumbnail upload destination.")
            client.upload_bytes(session.thumbnail_upload_url, _read_asset(thumbnail["path"]), content_type=thumbnail["mime_type"])
        if captions is not None:
            if not session.captions_upload_url:
                raise LinkedInApiUncertainError("LinkedIn omitted the requested captions upload destination.")
            client.upload_bytes(session.captions_upload_url, _read_asset(captions["path"]), content_type=captions["mime_type"])
        client.finalize_video_upload(session.asset_urn, session.upload_token or "", etags)
        self._set_state(connection, request_id, "upload_processing")
        status = client.get_asset_status("video", session.asset_urn)
        if status != "AVAILABLE":
            raise LinkedInProcessingUnknownError(f"LinkedIn video processing status is {status}.")
        self._store_asset_urns(connection, request_id, [session.asset_urn], "assets_uploaded")
        return [session.asset_urn]

    def _freeze_package(self, post: sqlite3.Row, author_urn: str) -> dict[str, Any]:
        package = _json_object(post["package_json"])
        publish_format = str(package.get("publish_format") or ("single_image" if post["image_source"] != "none" else "text"))
        base: dict[str, Any] = {
            "package_id": int(post["id"]), "package_version": int(post["package_version"]),
            "format": publish_format, "commentary": str(post["draft_text"]),
            "visibility": settings.linkedin_default_visibility, "author_urn": author_urn,
            "api_version": settings.linkedin_api_version,
        }
        assets: list[dict[str, Any]] = []
        if publish_format == "single_image":
            assets = [self._asset(str(post["image_path"] or ""), str(post["image_alt_text"] or ""), 0)]
        elif publish_format in {"multi_image", "video", "document"}:
            raw_assets = package.get("assets")
            if not isinstance(raw_assets, list):
                raise LinkedInPublishingError(f"{publish_format} package is missing approved assets.")
            assets = [
                self._asset(
                    str(item.get("path", "")), str(item.get("alt_text", "")), index,
                    str(item.get("title") or "") or None,
                    float(item["duration_seconds"]) if item.get("duration_seconds") is not None else None,
                    _asset_role(item.get("role")),
                )
                for index, item in enumerate(raw_assets) if isinstance(item, dict)
            ]
        if publish_format == "multi_image":
            MultiImagePublishPayload(**base, assets=[LinkedInMediaAsset(**asset) for asset in assets])
        elif publish_format == "video":
            primary = [asset for asset in assets if asset.get("role") == "primary"]
            thumbnails = [asset for asset in assets if asset.get("role") == "thumbnail"]
            captions = [asset for asset in assets if asset.get("role") == "captions"]
            if len(primary) != 1 or len(thumbnails) > 1 or len(captions) > 1:
                raise LinkedInPublishingError("Video packages require one video and at most one thumbnail and captions file.")
            VideoPublishPayload(
                **base, asset=LinkedInMediaAsset(**primary[0]),
                thumbnail=LinkedInMediaAsset(**thumbnails[0]) if thumbnails else None,
                captions=LinkedInMediaAsset(**captions[0]) if captions else None,
            )
        elif publish_format == "document":
            if len(assets) != 1:
                raise LinkedInPublishingError("Document packages require exactly one approved document.")
            base["title"] = str(package.get("document_title") or assets[0].get("title") or "")
            DocumentPublishPayload(**base, asset=LinkedInMediaAsset(**assets[0]))
        elif publish_format == "article":
            article_value = package.get("article")
            article: dict[str, Any] = dict(article_value) if isinstance(article_value, dict) else {}
            base.update(article)
            ArticlePublishPayload(**base)
            self._validate_public_https_url(str(base.get("article_url", "")))
        elif publish_format == "poll":
            poll_value = package.get("poll")
            poll: dict[str, Any] = dict(poll_value) if isinstance(poll_value, dict) else {}
            base.update(poll)
            PollPublishPayload(**base)
        elif publish_format not in {"text", "single_image"}:
            raise LinkedInPublishingError("Unsupported LinkedIn publication format.")
        return {"format": publish_format, "payload": base, "assets": assets}

    def _asset(self, raw_path: str, alt_text: str, order: int, title: str | None = None, duration_seconds: float | None = None, role: Literal["primary", "thumbnail", "captions"] = "primary") -> dict[str, Any]:
        if raw_path.startswith("supabase://"):
            stored_path = raw_path
            filename = raw_path.rsplit("/", 1)[-1]
            data = _read_asset(raw_path)
        else:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file() or not path.stat().st_size:
                raise LinkedInPublishingError("An approved publication asset is missing or empty.")
            stored_path = str(path)
            filename = path.name
            data = path.read_bytes()
        if not data:
            raise LinkedInPublishingError("An approved publication asset is missing or empty.")
        mime = _detect_mime_bytes(data, filename)
        size = len(data)
        if mime in {"image/jpeg", "image/png", "image/gif"}:
            if not alt_text.strip():
                raise LinkedInPublishingError("Approved image alt text is required.")
            if size > settings.linkedin_max_image_bytes:
                raise LinkedInPublishingError("Approved image exceeds the configured size limit.")
            width, height = _image_dimensions_bytes(data, mime)
            if width * height >= 36_152_320:
                raise LinkedInPublishingError("Approved image exceeds LinkedIn's pixel-count limit.")
        elif mime == "video/mp4":
            if size < 75 * 1024 or size > settings.linkedin_max_video_bytes:
                raise LinkedInPublishingError("Approved video is outside the configured LinkedIn size range.")
            if duration_seconds is None or not 3 <= duration_seconds <= 1800:
                raise LinkedInPublishingError("Approved video duration must be between 3 seconds and 30 minutes.")
        elif mime == "text/plain" and role == "captions":
            pass
        elif mime not in {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"}:
            raise LinkedInPublishingError("Unsupported LinkedIn publication asset MIME type.")
        elif size > settings.linkedin_max_document_bytes:
            raise LinkedInPublishingError("Approved document exceeds the configured size limit.")
        return LinkedInMediaAsset(path=stored_path, filename=filename, mime_type=mime, sha256=_sha256(data), size_bytes=size, alt_text=alt_text.strip() or None, title=title, order=order, duration_seconds=duration_seconds, role=role).model_dump()

    @staticmethod
    def _validate_package(post: sqlite3.Row) -> None:
        if post["status"] != "approved_for_later_posting":
            raise LinkedInPublishingError("Content package must be approved for later posting.")
        if not str(post["draft_text"] or "").strip():
            raise LinkedInPublishingError("Approved content package has no commentary.")
        if not _json_list(post["source_references_json"]):
            raise LinkedInPublishingError("Approved content package has no valid source references.")
        for claim in _json_list(post["factual_claims_json"]):
            if isinstance(claim, dict) and claim.get("confirmation_required"):
                raise LinkedInPublishingError("Approved content package still has an unresolved claim.")
        risk = _json_object(post["risk_assessment_json"])
        if not risk.get("validation_passed", False):
            raise LinkedInPublishingError("Approved content package failed claim validation.")

    @staticmethod
    def _base_provider_payload(frozen: dict[str, Any]) -> dict[str, Any]:
        return {
            "author": frozen["author_urn"], "commentary": frozen["commentary"],
            "visibility": frozen["visibility"],
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
        }

    @staticmethod
    def _validate_public_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise LinkedInPublishingError("Article source must be a public HTTPS URL.")
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            raise LinkedInPublishingError("Article source cannot target a local address.")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise LinkedInPublishingError(
                "Article source hostname could not be resolved safely."
            ) from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise LinkedInPublishingError("Article source cannot target a private or reserved address.")

    @staticmethod
    def _load_request(connection: sqlite3.Connection, request_id: int) -> sqlite3.Row:
        row = connection.execute(
            """SELECT requests.*, resolutions.decision AS resolution_decision,
                      resolutions.provider_post_id AS resolution_provider_post_id,
                      resolutions.resolved_at
               FROM linkedin_publish_requests AS requests
               LEFT JOIN linkedin_publish_resolutions AS resolutions ON resolutions.request_id=requests.id
               WHERE requests.id=?""",
            (request_id,),
        ).fetchone()
        if row is None:
            raise LinkedInPublishingError(f"Publish request id {request_id} does not exist.")
        return row

    def _request_result(self, row: sqlite3.Row, reused: bool = False) -> dict[str, Any]:
        resolution = None
        if "resolution_decision" in row.keys() and row["resolution_decision"]:
            resolution = {
                "decision": row["resolution_decision"],
                "provider_post_id": row["resolution_provider_post_id"],
                "resolved_at": row["resolved_at"],
            }
        return {
            "request_id": row["id"], "post_id": row["content_post_id"],
            "package_version": row["package_version"], "format": row["publish_format"],
            "status": row["status"], "commentary": _json_object(row["payload_json"]).get("commentary", ""),
            "visibility": row["visibility"], "payload_fingerprint": row["payload_hash"][:12],
            "assets": _json_list(row["asset_manifest_json"]), "provider_asset_urns": _json_list(row["provider_asset_urns_json"]),
            "provider_post_id": row["provider_post_id"], "safe_error_code": row["safe_error_code"],
            "safe_error_summary": row["safe_error_summary"], "expires_at": row["expires_at"], "reused": reused,
            "resolution": resolution,
        }

    @staticmethod
    def _set_state(connection: sqlite3.Connection, request_id: int, status: str, code: str | None = None, summary: str | None = None) -> None:
        connection.execute(
            "UPDATE linkedin_publish_requests SET status=?, safe_error_code=?, safe_error_summary=?, updated_at=? WHERE id=?",
            (status, code, safe_provider_message(summary) if summary else None, _now(), request_id),
        )
        LinkedInPublishingGateway._record_event(
            connection, request_id, "state_changed", "provider",
            {"status": status, "safe_error_code": code},
        )
        connection.commit()

    @staticmethod
    def _record_event(connection: sqlite3.Connection, request_id: int, event_type: str, stage: str, metadata: dict[str, Any] | None = None) -> None:
        connection.execute(
            """INSERT INTO linkedin_publish_events
               (request_id, event_type, stage, safe_metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (request_id, event_type, stage, _canonical_json(metadata or {}), _now()),
        )

    @staticmethod
    def _store_asset_urns(connection: sqlite3.Connection, request_id: int, urns: list[str], status: str) -> None:
        connection.execute(
            "UPDATE linkedin_publish_requests SET provider_asset_urns_json=?, status=?, updated_at=? WHERE id=?",
            (_canonical_json(urns), status, _now(), request_id),
        )
        LinkedInPublishingGateway._record_event(
            connection, request_id, "assets_recorded", "upload",
            {"status": status, "asset_count": len(urns)},
        )
        connection.commit()

    @staticmethod
    def _complete(connection: sqlite3.Connection, request_id: int, status: str, post_id: str, asset_urns: list[str]) -> None:
        connection.execute(
            """UPDATE linkedin_publish_requests SET status=?, provider_post_id=?,
               provider_asset_urns_json=?, safe_error_code=NULL, safe_error_summary=NULL,
               completed_at=?, updated_at=? WHERE id=?""",
            (status, post_id, _canonical_json(asset_urns), _now(), _now(), request_id),
        )
        LinkedInPublishingGateway._record_event(
            connection, request_id, "provider_completed", "publication",
            {"status": status, "asset_count": len(asset_urns), "provider_id_present": bool(post_id)},
        )
        connection.commit()

    @staticmethod
    def _validate_configuration(*, for_real: bool) -> None:
        if settings.linkedin_publish_mode not in {"disabled", "mock", "real"}:
            raise LinkedInPublishingError("LINKEDIN_PUBLISH_MODE is invalid.")
        if not re.fullmatch(r"\d{6}", settings.linkedin_api_version):
            raise LinkedInPublishingError("LINKEDIN_API_VERSION must use YYYYMM format.")
        if settings.linkedin_api_base_url.rstrip("/") != "https://api.linkedin.com":
            raise LinkedInPublishingError("LinkedIn API host is not allowlisted.")
        if settings.linkedin_default_visibility not in {"PUBLIC", "CONNECTIONS"}:
            raise LinkedInPublishingError("LinkedIn visibility is not allowlisted.")
        if for_real and (settings.linkedin_publish_mode != "real" or not settings.linkedin_real_publish_enabled):
            raise LinkedInPublishingError("Real LinkedIn publishing requires both configuration controls.")

    @staticmethod
    def _default_api_client(access_token: str) -> LinkedInApiClient:
        return LinkedInApiClient(
            access_token=access_token, api_version=settings.linkedin_api_version,
            restli_protocol_version=settings.linkedin_restli_protocol_version,
            api_base_url=settings.linkedin_api_base_url,
            timeout_seconds=settings.linkedin_request_timeout_seconds,
        )


def _coerce(database: DatabaseRef) -> tuple[sqlite3.Connection, bool]:
    return (database, False) if isinstance(database, sqlite3.Connection) else (connect(database), True)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _processing_unknown_status(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='linkedin_publish_requests'"
    ).fetchone()
    return "processing_unknown" if row and "processing_unknown" in str(row[0]) else "publish_uncertain"


def _validate_upload_not_expired(expires_at: int | None) -> None:
    """Reject expired provider instructions before any asset bytes are sent."""
    if expires_at is None:
        return
    now_milliseconds = int(datetime.now(UTC).timestamp() * 1000)
    if expires_at <= now_milliseconds:
        raise LinkedInApiRejectedError("LinkedIn media upload instructions have expired.")


def _asset_role(value: Any) -> Literal["primary", "thumbnail", "captions"]:
    role = str(value or "primary")
    if role == "thumbnail":
        return "thumbnail"
    if role == "captions":
        return "captions"
    if role == "primary":
        return "primary"
    raise LinkedInPublishingError("Unsupported approved media asset role.")


def _detect_mime(path: Path) -> str:
    return _detect_mime_bytes(path.read_bytes(), path.name)


def _detect_mime_bytes(data: bytes, filename: str) -> str:
    head = data[:16]
    suffix = Path(filename).suffix.lower()
    if head.startswith(b"\xff\xd8\xff") and suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n") and suffix == ".png":
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")) and suffix == ".gif":
        return "image/gif"
    if len(head) >= 8 and head[4:8] == b"ftyp" and suffix == ".mp4":
        return "video/mp4"
    if head.startswith(b"%PDF") and suffix == ".pdf":
        return "application/pdf"
    if suffix == ".srt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LinkedInPublishingError("Caption file must be UTF-8 text.") from exc
        return "text/plain"
    guessed = mimetypes.guess_type(filename)[0]
    allowed_office = {
        ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".ppt": "application/vnd.ms-powerpoint", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    if suffix in allowed_office and guessed == allowed_office[suffix]:
        return allowed_office[suffix]
    raise LinkedInPublishingError("Asset extension and detected MIME type do not match an allowlisted format.")


def _image_dimensions(path: Path, mime: str) -> tuple[int, int]:
    return _image_dimensions_bytes(path.read_bytes(), mime)


def _image_dimensions_bytes(data: bytes, mime: str) -> tuple[int, int]:
    if mime == "image/png":
        return struct.unpack(">II", data[16:24])
    if mime == "image/gif":
        return struct.unpack("<HH", data[6:10])
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            return int.from_bytes(data[index + 7:index + 9], "big"), int.from_bytes(data[index + 5:index + 7], "big")
        index += max(length + 2, 2)
    raise LinkedInPublishingError("Could not validate approved image dimensions.")


def _read_asset(path_or_uri: str) -> bytes:
    try:
        return read_asset_bytes(path_or_uri)
    except (OSError, SupabaseStorageError) as exc:
        raise LinkedInPublishingError(
            "An approved publication asset is missing or unavailable."
        ) from exc
