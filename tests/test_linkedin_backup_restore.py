"""Safe SQLite backup and restore certification for LinkedIn state."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from db.backup import backup_database, restore_database
from db.database import connect, initialize_database
from integrations.linkedin_publishing_gateway import LinkedInPublishingGateway


def test_backup_restore_preserves_encrypted_credentials_and_history_without_resuming_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    initialize_database(source)
    now = datetime.now(UTC)
    with connect(source) as connection:
        prospect = connection.execute(
            "INSERT INTO prospects (name, status, source, created_at, updated_at) VALUES ('Backup', 'not_contacted', 'manual', ?, ?)",
            (now.isoformat(), now.isoformat()),
        ).lastrowid
        post_id = connection.execute(
            """INSERT INTO content_posts
               (draft_text, image_source, status, created_at, updated_at)
               VALUES ('Approved', 'none', 'draft', ?, ?)""",
            (now.isoformat(), now.isoformat()),
        ).lastrowid
        credential_id = connection.execute(
            """INSERT INTO linkedin_credentials
               (encrypted_access_token, encrypted_refresh_token, oidc_subject,
                granted_scopes, authorized_at, access_token_expires_at, status)
               VALUES ('encrypted-value', NULL, 'member',
                       '[\"openid\",\"profile\",\"w_member_social\"]', ?, ?, 'active')""",
            (now.isoformat(), now.isoformat()),
        ).lastrowid
        connection.execute(
            """INSERT INTO linkedin_publish_requests
               (content_post_id, package_version, publish_format, status,
                payload_json, payload_hash, asset_manifest_json, idempotency_key,
                credential_id, author_urn, visibility, api_version, expires_at,
                created_at, updated_at)
               VALUES (?, 1, 'text', 'publishing_in_progress', '{}', ?, '[]', ?,
                       ?, 'urn:li:person:member', 'PUBLIC', '202601', ?, ?, ?)""",
            (
                post_id,
                "0" * 64,
                f"restore:{prospect}",
                credential_id,
                (now + timedelta(minutes=10)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.commit()

    backup_database(source, backup)
    restore_database(backup, restored)
    with connect(restored) as connection:
        credential = connection.execute(
            "SELECT encrypted_access_token, granted_scopes FROM linkedin_credentials"
        ).fetchone()
        assert credential["encrypted_access_token"] == "encrypted-value"
        assert "w_member_social" in credential["granted_scopes"]
        assert connection.execute("SELECT COUNT(*) FROM linkedin_publish_requests").fetchone()[0] == 1

    class NoProvider:
        def __call__(self, _token: str) -> None:
            raise AssertionError("Restore reconciliation must not create a provider client.")

    gateway = LinkedInPublishingGateway(api_client_factory=NoProvider())
    assert gateway.reconcile_stale_in_progress(restored) == 1
    with connect(restored) as connection:
        request = connection.execute("SELECT status FROM linkedin_publish_requests").fetchone()
        assert request["status"] == "publish_uncertain"


def test_backup_restore_rejects_missing_source(tmp_path: Path) -> None:
    from db.backup import DatabaseBackupError

    try:
        backup_database(tmp_path / "missing.db", tmp_path / "backup.db")
    except DatabaseBackupError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Missing source should be rejected.")
