"""Phase 8G-B3 rich-format validation tests."""

import pytest
from pydantic import ValidationError

from integrations.linkedin_publish_models import (
    LinkedInMediaAsset,
    MultiImagePublishPayload,
    PollPublishPayload,
)


def asset(name: str, order: int) -> LinkedInMediaAsset:
    return LinkedInMediaAsset(
        path=f"/tmp/{name}.png", filename=f"{name}.png", mime_type="image/png",
        sha256=(str(order + 1) * 64), size_bytes=10, alt_text=name, order=order,
    )


def test_multi_image_requires_at_least_two_images() -> None:
    with pytest.raises(ValidationError):
        MultiImagePublishPayload(package_id=1, package_version=1, commentary="x", author_urn="urn:li:person:1", api_version="202606", assets=[asset("one", 0)])


def test_multi_image_rejects_duplicate_assets() -> None:
    duplicate = asset("one", 0)
    with pytest.raises(ValidationError, match="distinct"):
        MultiImagePublishPayload(package_id=1, package_version=1, commentary="x", author_urn="urn:li:person:1", api_version="202606", assets=[duplicate, duplicate.model_copy(update={"order": 1})])


def test_multi_image_preserves_contiguous_order() -> None:
    result = MultiImagePublishPayload(package_id=1, package_version=1, commentary="x", author_urn="urn:li:person:1", api_version="202606", assets=[asset("one", 0), asset("two", 1)])
    assert [item.filename for item in result.assets] == ["one.png", "two.png"]


@pytest.mark.parametrize("options", [["one"], ["one", "one"], ["", "two"], ["x" * 31, "two"]])
def test_poll_rejects_invalid_options(options: list[str]) -> None:
    with pytest.raises(ValidationError):
        PollPublishPayload(package_id=1, package_version=1, commentary="x", author_urn="urn:li:person:1", api_version="202606", question="Question?", options=options, duration="ONE_DAY")


def test_poll_accepts_official_option_count_and_duration() -> None:
    poll = PollPublishPayload(package_id=1, package_version=1, commentary="x", author_urn="urn:li:person:1", api_version="202606", question="Question?", options=["One", "Two"], duration="SEVEN_DAYS")
    assert poll.options == ["One", "Two"]
