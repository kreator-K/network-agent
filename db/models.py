"""Pydantic models for database-facing records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    "linkedin_connection_request",
    "reply_logged",
    "meeting_confirmed",
    "note",
]
InteractionDirection = Literal["outbound_draft", "inbound_logged"]
InteractionStatus = Literal["drafted", "sent_manually", "discarded"]
RefinableAgentName = Literal["outreach_draft_agent", "content_inspiration_agent"]
ContentPostImageSource = Literal["uploaded", "generated", "none"]
ContentPostStatus = Literal[
    "draft",
    "saved",
    "approved_for_later_posting",
    "discarded",
]
SignalSourceType = Literal["rss", "atom", "auto_feed"]
SignalSourceApprovalStatus = Literal["pending", "approved", "rejected"]
SignalStatus = Literal[
    "fetched", "normalized", "scored", "ineligible", "duplicate", "failed"
]
SignalEligibilityStatus = Literal["pending", "eligible", "ineligible", "scoring_failed"]
SignalScoringMode = Literal["deterministic", "model_assisted", "deterministic_fallback"]
ContentOpportunityStatus = Literal["candidate", "saved", "selected", "dismissed", "expired"]
ContentFeedbackType = Literal[
    "more_like_this", "less_like_this", "save", "dismiss", "not_relevant",
    "too_generic", "too_risky", "good_angle", "wrong_audience",
]


def _clean_profile_list(values: list[str]) -> list[str]:
    cleaned = [" ".join(value.strip().split()) for value in values]
    if any(not value for value in cleaned):
        raise ValueError("Profile lists cannot contain empty values.")
    return cleaned


class PersonalBrandProfileData(BaseModel):
    """User-authorized, versioned personal-brand profile content."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    professional_identity: str = Field(min_length=1, max_length=500)
    current_program: str | None = Field(default=None, max_length=300)
    institutions: list[str] = Field(default_factory=list, max_length=20)
    career_focus: list[str] = Field(default_factory=list, max_length=20)
    content_pillars: list[str] = Field(min_length=1, max_length=30)
    target_audiences: list[str] = Field(min_length=1, max_length=30)
    preferred_tone: list[str] = Field(default_factory=list, max_length=20)
    preferred_depth: str | None = Field(default=None, max_length=200)
    preferred_post_formats: list[str] = Field(default_factory=list, max_length=20)
    humor_preferences: list[str] = Field(default_factory=list, max_length=20)
    personal_experience_boundaries: list[str] = Field(default_factory=list, max_length=30)
    verified_experiences: list[str] = Field(default_factory=list, max_length=50)
    allowed_personal_claims: list[str] = Field(default_factory=list, max_length=50)
    claims_requiring_confirmation: list[str] = Field(default_factory=list, max_length=50)
    topics_to_avoid: list[str] = Field(default_factory=list, max_length=50)
    posting_preferences: list[str] = Field(default_factory=list, max_length=20)
    networking_goals: list[str] = Field(default_factory=list, max_length=30)
    desired_network_types: list[str] = Field(default_factory=list, max_length=30)
    industries_of_interest: list[str] = Field(default_factory=list, max_length=30)
    companies_of_interest: list[str] = Field(default_factory=list, max_length=50)
    geographic_preferences: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "institutions", "career_focus", "content_pillars", "target_audiences",
        "preferred_tone", "preferred_post_formats", "humor_preferences",
        "personal_experience_boundaries", "verified_experiences",
        "allowed_personal_claims", "claims_requiring_confirmation", "topics_to_avoid",
        "posting_preferences", "networking_goals", "desired_network_types",
        "industries_of_interest", "companies_of_interest", "geographic_preferences",
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _clean_profile_list(values)

    @field_validator(
        "schema_version", "professional_identity", "current_program",
        "preferred_depth", "notes", mode="before",
    )
    @classmethod
    def normalize_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Profile text fields must be strings.")
        cleaned = " ".join(value.strip().split())
        return cleaned or None


class DataLayerModel(BaseModel):
    """Base config for SQLite-facing Pydantic models."""

    model_config = ConfigDict(extra="forbid")


class PersonalBrandProfile(DataLayerModel):
    """Immutable SQLite version of a personal-brand profile."""

    id: int | None = None
    version: int = Field(ge=1)
    schema_version: str
    profile_json: str
    profile_hash: str
    is_active: bool = False
    created_at: str
    activated_at: str | None = None


class SignalSource(DataLayerModel):
    """Explicitly approved public RSS or Atom source configuration."""

    id: int | None = None
    name: str
    source_type: SignalSourceType
    url: str
    approval_status: SignalSourceApprovalStatus = "pending"
    enabled: bool = False
    approved_at: str | None = None
    last_fetched_at: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    last_fetch_status: str | None = None
    last_error: str | None = None
    config_json: str = "{}"
    created_at: str
    updated_at: str


class Signal(DataLayerModel):
    """Normalized public feed item with immutable source provenance."""

    id: int | None = None
    source_id: int
    external_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    summary: str | None = None
    author: str | None = None
    published_at: str | None = None
    updated_at_source: str | None = None
    fetched_at: str
    content_hash: str | None = None
    dedupe_key: str | None = None
    duplicate_of_id: int | None = None
    raw_payload_json: str
    normalized_json: str | None = None
    status: SignalStatus
    error_message: str | None = None
    profile_version: int | None = Field(default=None, ge=1)
    scoring_config_version: int | None = Field(default=None, ge=1)
    score_json: str | None = None
    total_score: float | None = Field(default=None, ge=0, le=100)
    scoring_confidence: float | None = Field(default=None, ge=0, le=1)
    scoring_mode: SignalScoringMode | None = None
    scored_at: str | None = None
    eligibility_status: SignalEligibilityStatus = "pending"
    eligibility_reasons_json: str | None = None
    created_at: str
    updated_at: str


class SignalScoringConfig(DataLayerModel):
    """Immutable scoring configuration version used by signal evaluations."""

    id: int | None = None
    version: int = Field(ge=1)
    config_json: str
    config_hash: str
    is_active: bool = False
    created_at: str
    activated_at: str | None = None


class DeterministicSignalScores(BaseModel):
    """Auditable rule-based signal scores, each bounded from zero to 100."""

    model_config = ConfigDict(extra="forbid")
    topic_relevance: float = Field(ge=0, le=100)
    audience_relevance: float = Field(ge=0, le=100)
    credibility: float = Field(ge=0, le=100)
    freshness: float = Field(ge=0, le=100)
    originality: float = Field(ge=0, le=100)
    personal_angle: float = Field(ge=0, le=100)
    factual_risk: float = Field(ge=0, le=100)
    generic_commentary_risk: float = Field(ge=0, le=100)
    promotional_content_penalty: float = Field(ge=0, le=100)
    topic_saturation_penalty: float = Field(ge=0, le=100)


class SemanticSignalScores(BaseModel):
    """Validated optional semantic model judgment; it never bypasses hard gates."""

    model_config = ConfigDict(extra="forbid")
    semantic_profile_relevance: float = Field(ge=0, le=100)
    personal_angle_availability: float = Field(ge=0, le=100)
    audience_interest_potential: float = Field(ge=0, le=100)
    humor_suitability: float = Field(ge=0, le=100)
    generic_commentary_risk: float = Field(ge=0, le=100)
    factual_risk: float = Field(ge=0, le=100)
    suggested_treatment: str = Field(max_length=300)
    explanation: str = Field(max_length=1000)
    confidence: float = Field(ge=0, le=1)


class SignalScoreBreakdown(BaseModel):
    """Stored scoring decision including component scores, penalties, and reasons."""

    model_config = ConfigDict(extra="forbid")
    deterministic: DeterministicSignalScores
    semantic: SemanticSignalScores | None = None
    final_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    formula_version: str
    scoring_config_version: int = Field(ge=1)
    profile_version: int = Field(ge=1)
    mode: SignalScoringMode
    reasons: list[str] = Field(default_factory=list, max_length=30)
    model_identifier: str | None = None
    fallback_reason: str | None = None


class ContentOpportunity(DataLayerModel):
    """Reviewable pre-draft content angle traced to one or more stored signals."""

    id: int | None = None
    primary_signal_id: int
    supporting_signal_ids_json: str = "[]"
    profile_version: int = Field(ge=1)
    scoring_config_version: int = Field(ge=1)
    headline: str
    suggested_angle: str
    rationale: str
    target_audience: str
    recommended_format: str
    suggested_treatment: str
    humor_suitability: float = Field(ge=0, le=100)
    factual_risk: float = Field(ge=0, le=100)
    generic_commentary_risk: float = Field(ge=0, le=100)
    score_json: str
    total_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    source_references_json: str
    status: ContentOpportunityStatus = "candidate"
    created_at: str
    updated_at: str
    decided_at: str | None = None
    decision_reason: str | None = None
    metadata_json: str = "{}"


class ContentPreferenceFeedback(DataLayerModel):
    """Explicit user feedback retained for future human-approved refinement only."""

    id: int | None = None
    target_type: Literal["signal", "opportunity"]
    target_id: int
    feedback_type: ContentFeedbackType
    note: str | None = None
    source: str = "telegram"
    created_at: str


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
    status: InteractionStatus | None = None
    source: str | None = None
    created_at: str
    updated_at: str


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
    topic: str | None = None
    draft_text: str
    image_source: ContentPostImageSource = "none"
    image_path: str | None = None
    inspiration_source_notes: str | None = None
    status: ContentPostStatus = "draft"
    engagement_metric: float | None = None
    created_at: str
    updated_at: str


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
    status: Literal["confirmed", "calendar_created", "calendar_failed"] = "confirmed"
    created_at: str
