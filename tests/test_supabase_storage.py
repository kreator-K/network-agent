"""Tests for private Supabase content storage."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from integrations.supabase_storage import SupabaseStorageError, SupabaseStorageGateway


def test_upload_image_returns_private_storage_reference() -> None:
    response = Mock(status_code=200)
    gateway = SupabaseStorageGateway(
        url="https://project.supabase.co",
        service_role_key="server-secret",
        bucket="content-images",
    )
    with patch("integrations.supabase_storage.requests.post", return_value=response) as post:
        result = gateway.upload_image(b"png-data", "image/png")
    assert result.startswith("supabase://content-images/studio/")
    assert result.endswith(".png")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer server-secret"
    assert "server-secret" not in result


def test_upload_image_rejects_unsupported_media_before_network() -> None:
    gateway = SupabaseStorageGateway(url="https://project.supabase.co", service_role_key="secret")
    with patch("integrations.supabase_storage.requests.post") as post:
        with pytest.raises(SupabaseStorageError, match="JPEG, PNG, and WebP"):
            gateway.upload_image(b"gif", "image/gif")
    post.assert_not_called()


def test_read_bytes_rejects_another_bucket() -> None:
    gateway = SupabaseStorageGateway(
        url="https://project.supabase.co",
        service_role_key="secret",
        bucket="content-images",
    )
    with pytest.raises(SupabaseStorageError, match="unexpected storage bucket"):
        gateway.read_bytes("supabase://other/image.png")
