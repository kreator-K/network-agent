"""Profile context extraction and personal-brand profile agent.

MVP simplification: this agent does not call an LLM. It structures only the
manual prospect fields the user has already provided. Future phases may route
richer profile text extraction through ModelOrchestrationAgent.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from db.database import (
    activate_personal_brand_profile_version,
    create_personal_brand_profile_version,
    get_active_personal_brand_profile_row,
    get_personal_brand_profile_by_id,
    get_personal_brand_profile_by_version,
    list_personal_brand_profile_rows,
    connect,
)
from db.models import PersonalBrandProfile, PersonalBrandProfileData, Prospect


CORE_CONTEXT_FIELDS = ("role_title", "company", "notes")


class ProfileContextAgent:
    """Extract safe personalization signals from user-provided context.

    Purpose:
        Identify usable facts from supplied prospect fields and notes without
        inventing missing context.
    Inputs:
        Prospect role title, company, location, and user-provided notes.
    Outputs:
        Prompt-ready personalization context and missing-field guidance.
    """

    def build_context(self, prospect: Prospect) -> dict[str, Any]:
        """Build structured context from manually supplied prospect fields."""
        talking_points = _extract_talking_points(prospect.notes)
        return {
            "role_title": _clean_optional(prospect.role_title),
            "company": _clean_optional(prospect.company),
            "location": _clean_optional(prospect.location),
            "talking_points": talking_points,
            "has_sufficient_context": _has_sufficient_context(prospect),
        }

    def summarize_for_prompt(self, context: dict[str, Any]) -> str:
        """Convert context into a clean prompt-ready text block."""
        lines: list[str] = []
        role_title = _clean_optional(context.get("role_title"))
        company = _clean_optional(context.get("company"))
        location = _clean_optional(context.get("location"))
        talking_points = context.get("talking_points")

        if role_title:
            lines.append(f"Role title: {role_title}")
        if company:
            lines.append(f"Company: {company}")
        if location:
            lines.append(f"Location: {location}")
        if isinstance(talking_points, list):
            clean_points = [
                point.strip()
                for point in talking_points
                if isinstance(point, str) and point.strip()
            ]
            if clean_points:
                lines.append("Talking points:")
                lines.extend(f"- {point}" for point in clean_points)

        return "\n".join(lines)

    def flag_insufficient_context(self, prospect: Prospect) -> dict[str, Any]:
        """Return missing-field guidance for stronger personalization."""
        context = self.build_context(prospect)
        missing_fields = [
            field
            for field in CORE_CONTEXT_FIELDS
            if not _clean_optional(getattr(prospect, field))
        ]
        sufficient = bool(context["has_sufficient_context"])
        return {
            "sufficient": sufficient,
            "missing_fields": missing_fields,
            "recommendation": _recommendation_for_missing_fields(missing_fields),
        }

    def validate_personal_brand_profile(
        self,
        profile: PersonalBrandProfileData | dict[str, Any],
    ) -> PersonalBrandProfileData:
        """Validate user-authored profile data without using a model."""
        if isinstance(profile, PersonalBrandProfileData):
            return profile
        return PersonalBrandProfileData.model_validate(profile)

    def save_profile(
        self,
        profile: PersonalBrandProfileData | dict[str, Any],
        database: sqlite3.Connection | str | Path,
        activate: bool = True,
    ) -> PersonalBrandProfile:
        """Append a profile version and optionally make it active."""
        validated = self.validate_personal_brand_profile(profile)
        connection, should_close = _coerce_connection(database)
        try:
            row = create_personal_brand_profile_version(
                connection,
                validated,
                activate=activate,
            )
            connection.commit()
            return _profile_from_row(row)
        finally:
            if should_close:
                connection.close()

    def get_active_profile(
        self,
        database: sqlite3.Connection | str | Path,
    ) -> PersonalBrandProfile | None:
        """Return the active profile, or None before profile setup."""
        connection, should_close = _coerce_connection(database)
        try:
            row = get_active_personal_brand_profile_row(connection)
            return _profile_from_row(row) if row is not None else None
        finally:
            if should_close:
                connection.close()

    def get_profile(
        self,
        version: int,
        database: sqlite3.Connection | str | Path,
    ) -> PersonalBrandProfile:
        """Return one immutable profile version."""
        connection, should_close = _coerce_connection(database)
        try:
            row = get_personal_brand_profile_by_version(connection, version)
            if row is None:
                raise PersonalBrandProfileError(
                    f"Personal-brand profile version {version} does not exist."
                )
            return _profile_from_row(row)
        finally:
            if should_close:
                connection.close()

    def activate_profile(
        self,
        version: int,
        database: sqlite3.Connection | str | Path,
    ) -> PersonalBrandProfile:
        """Atomically activate an existing immutable profile version."""
        connection, should_close = _coerce_connection(database)
        try:
            active = activate_personal_brand_profile_version(connection, version)
            if active is None:
                raise PersonalBrandProfileError(
                    f"Personal-brand profile version {version} does not exist."
                )
            connection.commit()
            return _profile_from_row(active)
        finally:
            if should_close:
                connection.close()

    def build_personal_brand_context(
        self,
        profile: PersonalBrandProfile | PersonalBrandProfileData,
    ) -> str:
        """Render deterministic profile context for future prompts."""
        data = _profile_data_from_record(profile)
        fields: list[tuple[str, str | list[str] | None]] = [
            ("Professional identity", data.professional_identity),
            ("Current program", data.current_program),
            ("Institutions", data.institutions),
            ("Career focus", data.career_focus),
            ("Content pillars", data.content_pillars),
            ("Target audiences", data.target_audiences),
            ("Preferred tone", data.preferred_tone),
            ("Preferred depth", data.preferred_depth),
            ("Post formats", data.preferred_post_formats),
            ("Voice sentence rhythm", data.voice_sentence_rhythm),
            ("Voice vocabulary to use", data.voice_vocabulary_to_use),
            ("Voice vocabulary to avoid", data.voice_vocabulary_to_avoid),
            ("Voice formatting rules", data.voice_formatting_rules),
            ("Voice point of view", data.voice_point_of_view),
            ("Voice reference notes", data.voice_reference_notes),
            ("Brand name", data.brand_name),
            ("Visual colors", data.visual_colors),
            ("Typography", data.typography),
            ("Logo usage", data.logo_usage),
            ("Imagery guidelines", data.imagery_guidelines),
            ("Visual direction", data.visual_direction),
            ("Content rules to follow", data.content_rules_do),
            ("Content rules to avoid", data.content_rules_avoid),
            ("CTA style", data.cta_style),
            ("Humor preferences", data.humor_preferences),
            ("Personal experience boundaries", data.personal_experience_boundaries),
            ("Verified experiences", data.verified_experiences),
            ("Allowed personal claims", data.allowed_personal_claims),
            ("Claims requiring confirmation", data.claims_requiring_confirmation),
            ("Topics to avoid", data.topics_to_avoid),
            ("Posting preferences", data.posting_preferences),
            ("Networking goals", data.networking_goals),
            ("Desired network types", data.desired_network_types),
            ("Industries of interest", data.industries_of_interest),
            ("Companies of interest", data.companies_of_interest),
            ("Geographic preferences", data.geographic_preferences),
            ("Profile notes", data.notes),
        ]
        lines: list[str] = []
        for label, value in fields:
            if isinstance(value, list) and value:
                lines.append(f"{label}: {', '.join(value)}")
            elif isinstance(value, str) and value:
                lines.append(f"{label}: {value}")
        return "\n".join(lines)

    def list_profile_versions(
        self,
        database: sqlite3.Connection | str | Path,
        limit: int = 10,
    ) -> list[PersonalBrandProfile]:
        """List immutable profile versions, newest first."""
        connection, should_close = _coerce_connection(database)
        try:
            return [
                _profile_from_row(row)
                for row in list_personal_brand_profile_rows(connection, limit)
            ]
        finally:
            if should_close:
                connection.close()

    def get_profile_by_id(
        self,
        profile_id: int,
        database: sqlite3.Connection | str | Path,
    ) -> PersonalBrandProfile:
        """Return an immutable profile version by database ID."""
        connection, should_close = _coerce_connection(database)
        try:
            row = get_personal_brand_profile_by_id(connection, profile_id)
            if row is None:
                raise PersonalBrandProfileError(
                    f"Personal-brand profile id {profile_id} does not exist."
                )
            return _profile_from_row(row)
        finally:
            if should_close:
                connection.close()

    def summarize_personal_brand_profile(
        self,
        profile: PersonalBrandProfile,
    ) -> dict[str, Any]:
        """Return a concise display-safe summary of a profile version."""
        data = _profile_data_from_record(profile)
        return {
            "id": profile.id,
            "version": profile.version,
            "schema_version": profile.schema_version,
            "is_active": profile.is_active,
            "created_at": profile.created_at,
            "activated_at": profile.activated_at,
            "professional_identity": data.professional_identity,
            "current_program": data.current_program,
            "institutions": data.institutions,
            "career_focus": data.career_focus,
            "content_pillars": data.content_pillars,
            "target_audiences": data.target_audiences,
            "preferred_tone": data.preferred_tone,
            "preferred_depth": data.preferred_depth,
            "voice_sentence_rhythm": data.voice_sentence_rhythm,
            "voice_vocabulary_to_use": data.voice_vocabulary_to_use,
            "voice_vocabulary_to_avoid": data.voice_vocabulary_to_avoid,
            "voice_formatting_rules": data.voice_formatting_rules,
            "voice_point_of_view": data.voice_point_of_view,
            "voice_reference_notes": data.voice_reference_notes,
            "brand_name": data.brand_name,
            "visual_colors": data.visual_colors,
            "typography": data.typography,
            "logo_usage": data.logo_usage,
            "imagery_guidelines": data.imagery_guidelines,
            "visual_direction": data.visual_direction,
            "content_rules_do": data.content_rules_do,
            "content_rules_avoid": data.content_rules_avoid,
            "cta_style": data.cta_style,
            "humor_preferences": data.humor_preferences,
            "personal_experience_boundaries": data.personal_experience_boundaries,
            "verified_experiences": data.verified_experiences,
            "allowed_personal_claims": data.allowed_personal_claims,
            "claims_requiring_confirmation": data.claims_requiring_confirmation,
            "topics_to_avoid": data.topics_to_avoid,
            "networking_goals": data.networking_goals,
            "industries_of_interest": data.industries_of_interest,
            "companies_of_interest": data.companies_of_interest,
            "geographic_preferences": data.geographic_preferences,
        }

    # Explicit names make the orchestrator API easy to read while retaining a
    # small set of profile operations in this existing agent.
    create_personal_brand_profile = save_profile
    get_active_personal_brand_profile = get_active_profile
    create_personal_brand_profile_version = save_profile
    activate_personal_brand_profile_version = activate_profile
    list_personal_brand_profile_versions = list_profile_versions
    render_personal_brand_context = build_personal_brand_context


def _extract_talking_points(notes: str | None) -> list[str]:
    cleaned = _clean_optional(notes)
    if cleaned is None:
        return []
    return [cleaned]


def _has_sufficient_context(prospect: Prospect) -> bool:
    available_count = sum(
        1 for field in CORE_CONTEXT_FIELDS if _clean_optional(getattr(prospect, field))
    )
    return available_count >= 2


def _recommendation_for_missing_fields(missing_fields: list[str]) -> str:
    if "notes" in missing_fields:
        return (
            "Add notes about how you found this person or a shared interest for "
            "a stronger connection request."
        )
    if "role_title" in missing_fields:
        return "Add the prospect's role title to make the outreach more specific."
    if "company" in missing_fields:
        return "Add the prospect's company to ground the outreach in context."
    return "Enough context is available for a personalized draft."


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = " ".join(value.strip().split())
    return cleaned or None


class PersonalBrandProfileError(ValueError):
    """Raised when a requested profile version is unavailable."""


def _coerce_connection(
    database: sqlite3.Connection | str | Path,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _profile_data_from_record(
    profile: PersonalBrandProfile | PersonalBrandProfileData,
) -> PersonalBrandProfileData:
    if isinstance(profile, PersonalBrandProfileData):
        return profile
    try:
        return PersonalBrandProfileData.model_validate(json.loads(profile.profile_json))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PersonalBrandProfileError("Stored personal-brand profile is invalid.") from exc


def _profile_from_row(row: sqlite3.Row) -> PersonalBrandProfile:
    return PersonalBrandProfile(
        id=row["id"],
        version=row["version"],
        schema_version=row["schema_version"],
        profile_json=row["profile_json"],
        profile_hash=row["profile_hash"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        activated_at=row["activated_at"],
    )
