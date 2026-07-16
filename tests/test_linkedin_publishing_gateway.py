"""Durable approval and rich-format LinkedIn publishing tests."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

import integrations.linkedin_publishing_gateway as gateway_module
from db.database import connect, initialize_database
from integrations.linkedin_api_client import LinkedInApiRejectedError, LinkedInApiUncertainError, LinkedInPostResult
from integrations.linkedin_oauth_callback import LinkedInCredentialStore
from integrations.linkedin_oauth_client import LinkedInTokenSet
from integrations.linkedin_publishing_gateway import LinkedInPublishingError, LinkedInPublishingGateway
from integrations.linkedin_publish_models import LinkedInUploadSession


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
)


class FakeApi:
    def __init__(self, *, uncertain: bool = False) -> None:
        self.calls: list[str] = []
        self.payloads: list[dict[str, Any]] = []
        self.uncertain = uncertain

    def initialize_image_upload(self, owner: str) -> LinkedInUploadSession:
        self.calls.append(f"initialize_image:{owner}")
        return LinkedInUploadSession(asset_urn=f"urn:li:image:{len(self.calls)}", upload_urls=["https://www.linkedin.com/dms-uploads/image"])

    def initialize_document_upload(self, owner: str) -> LinkedInUploadSession:
        self.calls.append(f"initialize_document:{owner}")
        return LinkedInUploadSession(asset_urn="urn:li:document:1", upload_urls=["https://www.linkedin.com/dms-uploads/document"])

    def initialize_video_upload(self, owner: str, size: int, *, upload_thumbnail: bool = False, upload_captions: bool = False) -> LinkedInUploadSession:
        self.calls.append(f"initialize_video:{owner}:{size}")
        return LinkedInUploadSession(asset_urn="urn:li:video:1", upload_urls=["https://www.linkedin.com/dms-uploads/video"], upload_token="upload-token")

    def upload_bytes(self, _url: str, _content: bytes, *, content_type: str, extra_headers: dict[str, str] | None = None) -> str:
        self.calls.append(f"upload:{content_type}")
        return "etag"

    def finalize_video_upload(self, _urn: str, _token: str, _etags: list[str]) -> None:
        self.calls.append("finalize_video")

    def get_asset_status(self, kind: str, _urn: str) -> str:
        self.calls.append(f"status:{kind}")
        return "AVAILABLE"

    def create_post(self, payload: dict[str, Any]) -> LinkedInPostResult:
        self.calls.append("create_post")
        self.payloads.append(payload)
        if self.uncertain:
            raise LinkedInApiUncertainError("timeout token=secret")
        return LinkedInPostResult("urn:li:share:123")


def _setup(tmp_path: Path, *, publish_format: str = "text", image_path: Path | None = None, package_extra: dict[str, Any] | None = None) -> tuple[Path, int, str]:
    database = tmp_path / "network.db"
    initialize_database(database)
    key = Fernet.generate_key().decode()
    with connect(database) as connection:
        LinkedInCredentialStore(connection, key).save(
            LinkedInTokenSet("access", None, 3600, "openid profile w_member_social"),
            {"sub": "member-1", "name": "Member"},
        )
        package = {"publish_format": publish_format, **(package_extra or {})}
        now = datetime.now(UTC).isoformat()
        cursor = connection.execute(
            """INSERT INTO content_posts (
                draft_text, image_source, image_path, status, package_version,
                package_json, source_references_json, factual_claims_json,
                risk_assessment_json, image_alt_text, approved_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'approved_for_later_posting', 1, ?, ?, '[]', ?, ?, ?, ?, ?)""",
            (
                "Exact approved commentary", "generated" if image_path else "none",
                str(image_path) if image_path else None, json.dumps(package),
                '[{"signal_id":1}]', '{"validation_passed":true,"factual_risk":0}',
                "Approved alt text" if image_path else None, now, now, now,
            ),
        )
        connection.commit()
        assert cursor.lastrowid is not None
        return database, cursor.lastrowid, key


def _gateway(monkeypatch: pytest.MonkeyPatch, key: str, mode: str, enabled: bool, api: FakeApi | None = None) -> LinkedInPublishingGateway:
    monkeypatch.setattr(gateway_module, "settings", replace(gateway_module.settings, linkedin_token_encryption_key=key, linkedin_publish_mode=mode, linkedin_real_publish_enabled=enabled))
    return LinkedInPublishingGateway(api_client_factory=(lambda _token: api or FakeApi()))


def test_disabled_mode_prepares_preview_but_confirmation_makes_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "disabled", False, api)
    preview = gateway.prepare_publish(post_id, database)
    result = gateway.confirm_publish(preview["request_id"], database)
    assert result == {"status": "disabled", "published": False, "message": "LinkedIn publishing is disabled. Nothing was published."}
    assert api.calls == []


def test_mock_mode_persists_deterministic_result_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "mock", False, api)
    preview = gateway.prepare_publish(post_id, database)
    result = gateway.confirm_publish(preview["request_id"], database)
    assert result["status"] == "published_mock"
    assert result["published"] is False
    assert api.calls == []
    assert gateway.get_request(preview["request_id"], database)["provider_post_id"].startswith("mock:")


def test_real_text_post_preserves_commentary_and_author(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    result = gateway.confirm_publish(preview["request_id"], database)
    assert result["provider_post_id"] == "urn:li:share:123"
    assert api.payloads[0]["commentary"] == "Exact approved commentary"
    assert api.payloads[0]["author"] == "urn:li:person:member-1"
    assert "content" not in api.payloads[0]


def test_single_image_upload_uses_provider_urn_and_preserves_alt_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(PNG)
    database, post_id, key = _setup(tmp_path, publish_format="single_image", image_path=image)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    result = gateway.confirm_publish(preview["request_id"], database)
    assert result["asset_urns"] == ["urn:li:image:1"]
    assert api.payloads[0]["content"]["media"] == {"id": "urn:li:image:1", "altText": "Approved alt text"}


def test_changed_image_blocks_confirmation_without_text_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(PNG)
    database, post_id, key = _setup(tmp_path, publish_format="single_image", image_path=image)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    image.write_bytes(PNG + b"changed")
    with pytest.raises(LinkedInPublishingError, match="asset changed"):
        gateway.confirm_publish(preview["request_id"], database)
    assert api.calls == []


def test_duplicate_preview_reuses_request_and_confirmation_replay_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "mock", False)
    first = gateway.prepare_publish(post_id, database)
    second = gateway.prepare_publish(post_id, database)
    assert second["request_id"] == first["request_id"] and second["reused"] is True
    gateway.confirm_publish(first["request_id"], database)
    with pytest.raises(LinkedInPublishingError, match="cannot be confirmed"):
        gateway.confirm_publish(first["request_id"], database)


def test_uncertain_post_is_durable_and_blocks_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "real", True, FakeApi(uncertain=True))
    preview = gateway.prepare_publish(post_id, database)
    with pytest.raises(LinkedInPublishingError, match="uncertain"):
        gateway.confirm_publish(preview["request_id"], database)
    request = gateway.get_request(preview["request_id"], database)
    assert request["status"] == "publish_uncertain"
    assert "secret" not in (request["safe_error_summary"] or "")
    with pytest.raises(LinkedInPublishingError):
        gateway.confirm_publish(preview["request_id"], database)


def test_multi_image_order_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    first.write_bytes(PNG)
    second.write_bytes(PNG + b"two")
    assets = [{"path": str(first), "alt_text": "One"}, {"path": str(second), "alt_text": "Two"}]
    database, post_id, key = _setup(tmp_path, publish_format="multi_image", package_extra={"assets": assets})
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    gateway.confirm_publish(preview["request_id"], database)
    images = api.payloads[0]["content"]["multiImage"]["images"]
    assert [item["altText"] for item in images] == ["One", "Two"]


def test_unapproved_package_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    with connect(database) as connection:
        connection.execute("UPDATE content_posts SET status='draft' WHERE id=?", (post_id,))
    with pytest.raises(LinkedInPublishingError, match="approved"):
        _gateway(monkeypatch, key, "disabled", False).prepare_publish(post_id, database)


def test_document_upload_and_post_use_returned_document_urn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "brief.pdf"
    document.write_bytes(b"%PDF-1.7 approved")
    package = {"assets": [{"path": str(document), "title": "Approved brief"}], "document_title": "Approved brief"}
    database, post_id, key = _setup(tmp_path, publish_format="document", package_extra=package)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    gateway.confirm_publish(preview["request_id"], database)
    assert api.payloads[0]["content"]["media"] == {"id": "urn:li:document:1", "title": "Approved brief"}


def test_video_upload_finalizes_before_post(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftyp" + b"0" * (75 * 1024))
    database, post_id, key = _setup(tmp_path, publish_format="video", package_extra={"assets": [{"path": str(video), "title": "Approved video", "duration_seconds": 30}]})
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    gateway.confirm_publish(preview["request_id"], database)
    assert api.calls.index("finalize_video") < api.calls.index("create_post")
    assert api.payloads[0]["content"]["media"]["id"] == "urn:li:video:1"


def test_article_payload_is_frozen_without_scraping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    article = {"article_url": "https://example.com/article", "title": "Approved title", "description": "Approved description"}
    database, post_id, key = _setup(tmp_path, publish_format="article", package_extra={"article": article})
    api = FakeApi()
    monkeypatch.setattr(gateway_module.socket, "getaddrinfo", lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    gateway.confirm_publish(preview["request_id"], database)
    assert api.payloads[0]["content"]["article"] == {"source": article["article_url"], "title": article["title"], "description": article["description"]}


def test_article_rejects_local_or_private_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    article = {"article_url": "https://localhost/private", "title": "Title", "description": "Description"}
    database, post_id, key = _setup(tmp_path, publish_format="article", package_extra={"article": article})
    with pytest.raises(LinkedInPublishingError, match="local"):
        _gateway(monkeypatch, key, "disabled", False).prepare_publish(post_id, database)


def test_article_rejects_unresolvable_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    article = {"article_url": "https://unresolved.example/article", "title": "Title", "description": "Description"}
    database, post_id, key = _setup(tmp_path, publish_format="article", package_extra={"article": article})
    monkeypatch.setattr(
        gateway_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(gateway_module.socket.gaierror()),
    )
    with pytest.raises(LinkedInPublishingError, match="resolved safely"):
        _gateway(monkeypatch, key, "disabled", False).prepare_publish(post_id, database)


def test_poll_payload_preserves_question_options_and_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    poll = {"question": "Which trade-off matters?", "options": ["Speed", "Quality"], "duration": "SEVEN_DAYS"}
    database, post_id, key = _setup(tmp_path, publish_format="poll", package_extra={"poll": poll})
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    gateway.confirm_publish(preview["request_id"], database)
    assert api.payloads[0]["content"]["poll"] == {"question": poll["question"], "options": [{"text": "Speed"}, {"text": "Quality"}], "settings": {"duration": "SEVEN_DAYS"}}


def test_image_upload_failure_never_falls_back_to_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(PNG)
    database, post_id, key = _setup(tmp_path, publish_format="single_image", image_path=image)

    class FailedImageApi(FakeApi):
        def initialize_image_upload(self, owner: str) -> LinkedInUploadSession:
            self.calls.append(f"initialize_image:{owner}")
            raise LinkedInApiRejectedError("image rejected")

    api = FailedImageApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    with pytest.raises(LinkedInPublishingError):
        gateway.confirm_publish(preview["request_id"], database)
    assert "create_post" not in api.calls
    assert gateway.get_request(preview["request_id"], database)["status"] == "image_upload_failed"


def test_expired_upload_instructions_block_asset_bytes_and_post(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(PNG)
    database, post_id, key = _setup(tmp_path, publish_format="single_image", image_path=image)

    class ExpiredApi(FakeApi):
        def initialize_image_upload(self, owner: str) -> LinkedInUploadSession:
            self.calls.append(f"initialize_image:{owner}")
            return LinkedInUploadSession(
                asset_urn="urn:li:image:expired",
                upload_urls=["https://www.linkedin.com/dms-uploads/image"],
                upload_url_expires_at=1,
            )

    api = ExpiredApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    with pytest.raises(LinkedInPublishingError):
        gateway.confirm_publish(preview["request_id"], database)
    assert not any(call.startswith("upload:") for call in api.calls)
    assert "create_post" not in api.calls


def test_processing_unknown_blocks_final_post_and_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "brief.pdf"
    document.write_bytes(b"%PDF-1.7 approved")
    database, post_id, key = _setup(
        tmp_path,
        publish_format="document",
        package_extra={"assets": [{"path": str(document), "title": "Brief"}], "document_title": "Brief"},
    )

    class ProcessingApi(FakeApi):
        def get_asset_status(self, kind: str, _urn: str) -> str:
            self.calls.append(f"status:{kind}")
            return "PROCESSING"

    api = ProcessingApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    with pytest.raises(LinkedInPublishingError, match="processing is unresolved"):
        gateway.confirm_publish(preview["request_id"], database)
    request = gateway.get_request(preview["request_id"], database)
    assert request["status"] == "processing_unknown"
    assert "create_post" not in api.calls
    with pytest.raises(LinkedInPublishingError, match="cannot be confirmed"):
        gateway.confirm_publish(preview["request_id"], database)


def test_manual_resolution_preserves_original_uncertain_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "real", True, FakeApi(uncertain=True))
    preview = gateway.prepare_publish(post_id, database)
    with pytest.raises(LinkedInPublishingError):
        gateway.confirm_publish(preview["request_id"], database)
    resolved = gateway.resolve_uncertain(
        preview["request_id"], True, database, provider_post_id="urn:li:share:manual"
    )
    assert resolved["status"] == "publish_uncertain"
    assert resolved["provider_post_id"] is None
    assert resolved["resolution"]["decision"] == "posted"
    assert resolved["resolution"]["provider_post_id"] == "urn:li:share:manual"
    with pytest.raises(LinkedInPublishingError, match="already resolved"):
        gateway.resolve_uncertain(preview["request_id"], False, database)


def test_startup_reconciliation_marks_interrupted_write_uncertain_without_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    api = FakeApi()
    gateway = _gateway(monkeypatch, key, "real", True, api)
    preview = gateway.prepare_publish(post_id, database)
    with connect(database) as connection:
        connection.execute(
            "UPDATE linkedin_publish_requests SET status='upload_in_progress' WHERE id=?",
            (preview["request_id"],),
        )
        connection.commit()
    assert gateway.reconcile_stale_in_progress(database) == 1
    request = gateway.get_request(preview["request_id"], database)
    assert request["status"] == "publish_uncertain"
    assert request["safe_error_code"] == "interrupted_write"
    assert api.calls == []


def test_confirmation_attempt_backpressure_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    monkeypatch.setattr(gateway_module, "settings", replace(
        gateway_module.settings,
        linkedin_token_encryption_key=key,
        linkedin_publish_mode="disabled",
        linkedin_real_publish_enabled=False,
        linkedin_max_confirmation_attempts=2,
    ))
    gateway = LinkedInPublishingGateway(api_client_factory=lambda _token: FakeApi())
    preview = gateway.prepare_publish(post_id, database)
    assert gateway.confirm_publish(preview["request_id"], database)["status"] == "disabled"
    assert gateway.confirm_publish(preview["request_id"], database)["status"] == "disabled"
    with pytest.raises(LinkedInPublishingError, match="attempt limit"):
        gateway.confirm_publish(preview["request_id"], database)


def test_concurrent_confirmation_claim_allows_one_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "mock", False)
    request_id = gateway.prepare_publish(post_id, database)["request_id"]

    def confirm() -> str:
        try:
            return gateway.confirm_publish(request_id, database)["status"]
        except LinkedInPublishingError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: confirm(), range(2)))
    assert sorted(results) == ["published_mock", "rejected"]
    with connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM linkedin_publish_events WHERE request_id=? AND event_type='request_claimed'",
            (request_id,),
        ).fetchone()[0] == 1


def test_published_request_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "mock", False)
    request_id = gateway.prepare_publish(post_id, database)["request_id"]
    gateway.confirm_publish(request_id, database)
    with connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE linkedin_publish_requests SET safe_error_summary='changed' WHERE id=?",
            (request_id,),
        )


def test_diagnostics_are_read_only_and_secret_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, post_id, key = _setup(tmp_path)
    gateway = _gateway(monkeypatch, key, "disabled", False)
    gateway.prepare_publish(post_id, database)
    before = database.read_bytes()
    result = gateway.diagnostics(database)
    after = database.read_bytes()
    assert result["mode"] == "disabled"
    assert result["pending"] == 1
    assert "access" not in json.dumps(result).lower()
    assert before == after
