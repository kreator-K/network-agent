"""Pydantic models for database-facing records."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProspectStatus = Literal[
    "not_contacted",
    "outreach_drafted",
    "connection_sent",
    "connected",
    "meeting_confirmed",
    "closed",
]
InteractionType = Literal[
    "outreach_draft",
    "follow_up_draft",
    "reply_logged",
    "meeting_confirmed",
    "note",
]
InteractionDirection = Literal["outbound_draft", "inbound_logged"]
RefinableAgentName = Literal["outreach_draft_agent", "content_inspiration_agent"]
ContentPostImageSource = Literal["user_upload", "generated", "none"]
ContentPostStatus = Literal["drafted", "approved", "posted", "rejected"]


class DataLayerModel(BaseModel):
    """Base config for SQLite-facing Pydantic models."""

    model_config = ConfigDict(extra="forbid")


class Prospect(DataLayerModel):
    """Prospect record added manually by the user."""

    id: int | None = None
    name: str
    profile_url: str | None = None
    location: str | None = None
    role_title: str | None = None
    company: str | None = None
    notes: str | None = None
    source: str = "manual"
    status: ProspectStatus = "not_contacted"
    last_touch_date: str | None = None
    created_at: str
    updated_at: str


class Interaction(DataLayerModel):
    """Drafted or logged prospect interaction."""

    id: int | None = None
    prospect_id: int
    interaction_type: InteractionType
    content: str | None = None
    direction: InteractionDirection
    created_at: str


class CoreIntentRule(DataLayerModel):
    """Core intent rule loaded from human-edited JSON into SQLite."""

    id: int | None = None
    rule_key: str
    rule_value: str
    description: str | None = None
    updated_at: str


class RefinableParameter(DataLayerModel):
    """Mutable refinement parameter owned by the SQLite data layer."""

    id: int | None = None
    agent_name: RefinableAgentName
    parameter_key: str
    parameter_value: str
    version: int = Field(ge=1)
    is_active: bool = True
    created_at: str


class RefinementHistoryEntry(DataLayerModel):
    """Append-only refinement history entry."""

    id: int | None = None
    agent_name: RefinableAgentName
    version: int = Field(ge=1)
    what_changed: str
    why: str
    metric_before: float | None = None
    metric_after: float | None = None
    diff_against_v1: str
    core_intent_check_passed: bool
    accepted: bool
    created_at: str


class ContentPost(DataLayerModel):
    """Drafted LinkedIn content post record."""

    id: int | None = None
    draft_text: str
    image_source: ContentPostImageSource = "none"
    image_path: str | None = None
    inspiration_source_notes: str | None = None
    status: ContentPostStatus = "drafted"
    engagement_metric: float | None = None
    created_at: str


class CalendarBlock(DataLayerModel):
    """Calendar block record tied to an explicitly confirmed prospect meeting."""

    id: int | None = None
    prospect_id: int
    scheduled_date: str
    start_time: str
    end_time: str | None = None
    timezone: str | None = None
    notes: str | None = None
    external_event_id: str | None = None
    created_at: str
