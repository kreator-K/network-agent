"""Typed frozen payloads for approval-first LinkedIn publishing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PublishFormat = Literal[
    "text", "single_image", "multi_image", "video", "document", "article", "poll"
]


class LinkedInMediaAsset(BaseModel):
    """One approved local asset frozen into a publication preview."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    alt_text: str | None = Field(default=None, max_length=4086)
    title: str | None = Field(default=None, max_length=400)
    duration_seconds: float | None = Field(default=None, gt=0)
    order: int = Field(default=0, ge=0)
    role: Literal["primary", "thumbnail", "captions"] = "primary"


class LinkedInUploadSession(BaseModel):
    """Validated provider upload instructions without durable upload URLs."""

    model_config = ConfigDict(extra="forbid")

    asset_urn: str = Field(min_length=1)
    upload_urls: list[str] = Field(min_length=1)
    parts: list["LinkedInUploadPart"] = Field(default_factory=list)
    upload_url_expires_at: int | None = None
    upload_token: str | None = None
    thumbnail_upload_url: str | None = None
    captions_upload_url: str | None = None


class LinkedInUploadPart(BaseModel):
    """One exact provider-issued byte range for a multipart upload."""

    model_config = ConfigDict(extra="forbid")

    upload_url: str = Field(min_length=1)
    first_byte: int = Field(ge=0)
    last_byte: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "LinkedInUploadPart":
        if self.last_byte < self.first_byte:
            raise ValueError("Upload byte range is invalid.")
        return self


class _PublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: int = Field(gt=0)
    package_version: int = Field(gt=0)
    commentary: str = Field(max_length=6000)
    visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"
    author_urn: str = Field(pattern=r"^urn:li:person:[^\s]+$")
    api_version: str = Field(pattern=r"^\d{6}$")


class MultiImagePublishPayload(_PublishPayload):
    format: Literal["multi_image"] = "multi_image"
    assets: list[LinkedInMediaAsset] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_assets(self) -> "MultiImagePublishPayload":
        if len({asset.sha256 for asset in self.assets}) != len(self.assets):
            raise ValueError("Multi-image assets must be distinct.")
        if [asset.order for asset in self.assets] != list(range(len(self.assets))):
            raise ValueError("Multi-image asset ordering must be contiguous.")
        return self


class VideoPublishPayload(_PublishPayload):
    format: Literal["video"] = "video"
    asset: LinkedInMediaAsset
    thumbnail: LinkedInMediaAsset | None = None
    captions: LinkedInMediaAsset | None = None

    @model_validator(mode="after")
    def validate_video(self) -> "VideoPublishPayload":
        if self.asset.mime_type != "video/mp4":
            raise ValueError("LinkedIn video packages require MP4 media.")
        if self.asset.duration_seconds is None or not 3 <= self.asset.duration_seconds <= 1800:
            raise ValueError("LinkedIn video duration must be between 3 and 1800 seconds.")
        if self.thumbnail is not None and not self.thumbnail.mime_type.startswith("image/"):
            raise ValueError("Video thumbnail must be an approved image.")
        if self.captions is not None and self.captions.mime_type != "text/plain":
            raise ValueError("Video captions must be an approved SRT text file.")
        return self


class DocumentPublishPayload(_PublishPayload):
    format: Literal["document"] = "document"
    asset: LinkedInMediaAsset
    title: str = Field(min_length=1, max_length=400)


class ArticlePublishPayload(_PublishPayload):
    format: Literal["article"] = "article"
    article_url: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=400)
    description: str = Field(min_length=1, max_length=1000)
    thumbnail_urn: str | None = None


class PollPublishPayload(_PublishPayload):
    format: Literal["poll"] = "poll"
    question: str = Field(min_length=1, max_length=140)
    options: list[str] = Field(min_length=2, max_length=4)
    duration: Literal["ONE_DAY", "THREE_DAYS", "SEVEN_DAYS", "FOURTEEN_DAYS"]

    @field_validator("options")
    @classmethod
    def validate_options(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 30 for value in cleaned):
            raise ValueError("Poll options must contain 1 to 30 characters.")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("Poll options must be distinct.")
        return cleaned


class LinkedInRichPublishResult(BaseModel):
    """Validated provider success returned to the gateway."""

    provider_post_id: str = Field(min_length=1)
    asset_urns: list[str] = Field(default_factory=list)
    status: Literal["published"] = "published"


class LinkedInRichPublishFailure(BaseModel):
    """Safe durable provider failure metadata."""

    code: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=1000)
    uncertain: bool = False
