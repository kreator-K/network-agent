"""Application orchestration layer for Network Growth Agent workflows."""

import sqlite3
import json
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from agents.calendar_agent import CalendarAgent
from agents.content_inspiration_agent import ContentInspirationAgent
from agents.outreach_draft_agent import AskType, OutreachDraftAgent
from agents.profile_context_agent import ProfileContextAgent
from agents.prospect_discovery_agent import ProspectDiscoveryAgent
from agents.refinement_loop_agent import RefinementLoopAgent
from agents.relationship_tracker_agent import RelationshipTrackerAgent
from agents.signal_intelligence_agent import SignalIntelligenceAgent
from db.database import connect
from db.models import ContentPost, PersonalBrandProfile, PersonalBrandProfileData, Prospect


DatabaseRef = str | Path
TrackerFactory = Callable[[DatabaseRef], Any]
BRAND_PROFILE_LIST_FIELDS = {
    "institutions",
    "career_focus",
    "content_pillars",
    "target_audiences",
    "preferred_tone",
    "preferred_post_formats",
    "humor_preferences",
    "personal_experience_boundaries",
    "verified_experiences",
    "allowed_personal_claims",
    "claims_requiring_confirmation",
    "topics_to_avoid",
    "posting_preferences",
    "networking_goals",
    "desired_network_types",
    "industries_of_interest",
    "companies_of_interest",
    "geographic_preferences",
}
BRAND_PROFILE_TEXT_FIELDS = {
    "professional_identity",
    "current_program",
    "preferred_depth",
    "notes",
}
SUPPORTED_BRAND_PROFILE_FIELDS = BRAND_PROFILE_LIST_FIELDS | BRAND_PROFILE_TEXT_FIELDS


class NetworkOrchestratorError(RuntimeError):
    """Raised when an orchestrated workflow fails with contextual metadata."""


class NetworkOrchestrator:
    """Coordinate Telegram handlers, specialist agents, and persistence.

    Telegram bot handlers should call this orchestrator rather than calling
    specialist agents directly. The orchestrator owns cross-agent workflow
    sequencing, while each specialist agent keeps its own domain logic.
    """

    def __init__(
        self,
        prospect_discovery_agent: Any | None = None,
        profile_context_agent: Any | None = None,
        outreach_draft_agent: Any | None = None,
        calendar_agent: Any | None = None,
        content_inspiration_agent: Any | None = None,
        refinement_loop_agent: Any | None = None,
        signal_intelligence_agent: Any | None = None,
        tracker_factory: TrackerFactory | None = None,
    ) -> None:
        """Create an orchestrator with injectable agents for tests."""
        self.prospect_discovery_agent = (
            prospect_discovery_agent or ProspectDiscoveryAgent()
        )
        self.profile_context_agent = profile_context_agent or ProfileContextAgent()
        self.outreach_draft_agent = outreach_draft_agent or OutreachDraftAgent()
        self.calendar_agent = calendar_agent or CalendarAgent()
        self.content_inspiration_agent = (
            content_inspiration_agent or ContentInspirationAgent()
        )
        self.refinement_loop_agent = refinement_loop_agent or RefinementLoopAgent()
        self.signal_intelligence_agent = signal_intelligence_agent or SignalIntelligenceAgent()
        self.tracker_factory = tracker_factory or RelationshipTrackerAgent

    def handle(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Legacy command-shaped entrypoint retained for scaffold handlers."""
        return {"command": command, "payload": payload, "status": "unimplemented"}

    def add_prospect(
        self,
        name: str,
        profile_url: str | None = None,
        location: str | None = None,
        role_title: str | None = None,
        company: str | None = None,
        notes: str | None = None,
        *,
        database: DatabaseRef,
    ) -> dict[str, Prospect | str]:
        """Add a prospect through manual intake validation."""
        try:
            tracker = self._tracker(database)
            prospect = self.prospect_discovery_agent.intake_prospect(
                name=name,
                profile_url=profile_url,
                location=location,
                role_title=role_title,
                company=company,
                notes=notes,
                tracker=tracker,
            )
            return {"prospect": prospect, "status": "added"}
        except Exception as exc:
            _raise_with_context("add_prospect", {"name": name}, exc)

    def discover_prospect_candidates(self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 20) -> list[dict[str, Any]]:
        """Extract only stored public-source candidates; no external profile fetching."""
        try:
            return [candidate.model_dump() for candidate in self.prospect_discovery_agent.extract_candidates_from_signals(database, limit)]
        except Exception as exc:
            _raise_with_context("discover_prospect_candidates", {"limit": limit}, exc)

    def list_prospect_candidates(self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 20) -> list[dict[str, Any]]:
        """Return review candidates pending explicit human approval."""
        try:
            return [candidate.model_dump() for candidate in self.prospect_discovery_agent.list_candidates(database, limit)]
        except Exception as exc:
            _raise_with_context("list_prospect_candidates", {}, exc)

    def approve_prospect_candidate(self, candidate_id: int, *, database: DatabaseRef) -> dict[str, Any]:
        """Add a candidate to CRM only after a direct user decision."""
        try:
            prospect = self.prospect_discovery_agent.approve_candidate(candidate_id, self._tracker(database), database)
            return {"candidate_id": candidate_id, "prospect": prospect}
        except Exception as exc:
            _raise_with_context("approve_prospect_candidate", {"candidate_id": candidate_id}, exc)

    def draft_outreach(
        self,
        prospect_id: int,
        ask_type: str,
        *,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Draft and log a LinkedIn connection request for manual sending."""
        try:
            tracker = self._tracker(database)
            prospect = tracker.get_prospect(prospect_id)
            context_guidance = self.profile_context_agent.flag_insufficient_context(
                prospect
            )
            context_warning: dict[str, Any] | None = (
                None
                if context_guidance.get("sufficient") is True
                else context_guidance
            )

            draft = self.outreach_draft_agent.draft_connection_request(
                prospect=prospect,
                ask_type=cast(AskType, ask_type),
            )
            interaction = tracker.log_interaction(
                prospect_id=prospect_id,
                interaction_type="outreach_draft",
                content=json.dumps(
                    {
                        "status": "drafted",
                        "ask_type": ask_type,
                        "draft_text": str(draft.get("draft_text", "")),
                        "source": "telegram",
                    },
                    sort_keys=True,
                ),
                direction="outbound_draft",
                status="drafted",
                source="telegram",
            )
            return {
                "draft": draft,
                "context_warning": context_warning,
                "draft_interaction_id": interaction.id,
            }
        except Exception as exc:
            _raise_with_context(
                "draft_outreach",
                {"prospect_id": prospect_id, "ask_type": ask_type},
                exc,
            )

    def draft_followup(
        self,
        prospect_id: int,
        *,
        database: DatabaseRef,
    ) -> dict[str, dict[str, Any]]:
        """Draft and log a LinkedIn follow-up message for manual sending."""
        try:
            tracker = self._tracker(database)
            prospect = tracker.get_prospect(prospect_id)
            history = tracker.get_prospect_history(prospect_id)
            draft = self.outreach_draft_agent.draft_followup_message(
                prospect=prospect,
                history=history,
            )
            interaction = tracker.log_interaction(
                prospect_id=prospect_id,
                interaction_type="follow_up_draft",
                content=json.dumps(
                    {
                        "status": "drafted",
                        "draft_text": str(draft.get("draft_text", "")),
                        "source": "telegram",
                    },
                    sort_keys=True,
                ),
                direction="outbound_draft",
                status="drafted",
                source="telegram",
            )
            return {"draft": draft, "draft_interaction_id": interaction.id}
        except Exception as exc:
            _raise_with_context("draft_followup", {"prospect_id": prospect_id}, exc)

    def mark_outreach_sent(
        self,
        prospect_id: int,
        ask_type: str | None = None,
        draft_text: str | None = None,
        source: str = "telegram_button",
        draft_interaction_id: int | None = None,
        *,
        database: DatabaseRef,
    ) -> dict[str, Prospect | str]:
        """Mark manually sent outreach after explicit Telegram approval."""
        try:
            tracker = self._tracker(database)
            if hasattr(tracker, "mark_outreach_manually_sent"):
                prospect = tracker.mark_outreach_manually_sent(
                    prospect_id=prospect_id,
                    draft_interaction_id=draft_interaction_id,
                    ask_type=ask_type,
                    draft_text=draft_text,
                    source=source,
                )
                return {"prospect": prospect, "status": "sent_manually"}
            if draft_interaction_id is not None:
                tracker.update_interaction_status(draft_interaction_id, "sent_manually")
            interaction_content = json.dumps(
                {
                    "status": "sent_manually",
                    "ask_type": ask_type,
                    "draft_text": draft_text,
                    "source": source,
                },
                sort_keys=True,
            )
            tracker.log_interaction(
                prospect_id=prospect_id,
                interaction_type="linkedin_connection_request",
                content=interaction_content,
                direction="outbound_draft",
                status="sent_manually",
                source=source,
            )
            prospect = tracker.update_status(prospect_id, "connection_sent")
            return {"prospect": prospect, "status": "sent_manually"}
        except Exception as exc:
            _raise_with_context(
                "mark_outreach_sent",
                {"prospect_id": prospect_id},
                exc,
            )

    def discard_outreach_draft(
        self,
        interaction_id: int,
        *,
        database: DatabaseRef,
    ) -> dict[str, Any]:
        """Mark an outreach/follow-up draft discarded without touching cadence."""
        try:
            tracker = self._tracker(database)
            interaction = tracker.update_interaction_status(interaction_id, "discarded")
            return {"interaction": interaction, "status": "discarded"}
        except Exception as exc:
            _raise_with_context(
                "discard_outreach_draft",
                {"interaction_id": interaction_id},
                exc,
            )

    def get_followups_due(self, *, database: DatabaseRef) -> list[dict[str, Any]]:
        """Return due follow-ups formatted for Telegram display."""
        try:
            tracker = self._tracker(database)
            prospects = tracker.get_prospects_due_for_followup()
            return [_format_due_followup(prospect) for prospect in prospects]
        except Exception as exc:
            _raise_with_context("get_followups_due", {}, exc)

    def confirm_meeting(
        self,
        prospect_id: int,
        meeting_date: str,
        start_time: str,
        end_time: str | None = None,
        timezone: str | None = None,
        notes: str | None = None,
        *,
        database: DatabaseRef,
    ) -> dict[str, object]:
        """Record an explicitly confirmed meeting and attempt calendar sync."""
        try:
            tracker = self._tracker(database)
            return self.calendar_agent.confirm_meeting(
                prospect_id=prospect_id,
                meeting_date=meeting_date,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                notes=notes,
                tracker=tracker,
            )
        except Exception as exc:
            _raise_with_context(
                "confirm_meeting",
                {"prospect_id": prospect_id, "meeting_date": meeting_date},
                exc,
            )

    def draft_content_post(
        self,
        topic: str,
        inspiration_notes: str | None = None,
        user_image_path: str | None = None,
        generate_image: bool = False,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, ContentPost]:
        """Draft a LinkedIn post and save it for human review."""
        try:
            draft = self.content_inspiration_agent.draft_post(
                topic=topic,
                inspiration_notes=inspiration_notes,
                user_image_path=user_image_path,
                generate_image=generate_image,
            )
            post = self.content_inspiration_agent.save_draft_to_db(
                draft=draft,
                database=database,
            )
            return {"post": post}
        except Exception as exc:
            _raise_with_context("draft_content_post", {"topic": topic}, exc)

    def get_pending_content_drafts(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> list[dict[str, Any]]:
        """Return pending content drafts formatted for Telegram display."""
        try:
            drafts = self.content_inspiration_agent.get_pending_drafts(database)
            return [draft.model_dump() for draft in drafts]
        except Exception as exc:
            _raise_with_context("get_pending_content_drafts", {}, exc)

    def add_signal_source(
        self,
        name: str,
        url: str,
        source_type: str = "auto_feed",
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Store one public feed source as pending explicit approval."""
        try:
            source = self.signal_intelligence_agent.add_source(
                name=name,
                url=url,
                source_type=source_type,
                database=database,
            )
            return source.model_dump()
        except Exception as exc:
            _raise_with_context("add_signal_source", {"name": name}, exc)

    def approve_signal_source(
        self,
        source_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Approve a source without starting any background scan."""
        try:
            return self.signal_intelligence_agent.set_source_approval(
                source_id,
                "approved",
                database,
            ).model_dump()
        except Exception as exc:
            _raise_with_context("approve_signal_source", {"source_id": source_id}, exc)

    def reject_signal_source(
        self,
        source_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Reject a source and keep it disabled for auditability."""
        try:
            return self.signal_intelligence_agent.set_source_approval(
                source_id,
                "rejected",
                database,
            ).model_dump()
        except Exception as exc:
            _raise_with_context("reject_signal_source", {"source_id": source_id}, exc)

    def set_signal_source_enabled(
        self,
        source_id: int,
        enabled: bool,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Enable or disable an approved signal source."""
        try:
            return self.signal_intelligence_agent.set_source_enabled(
                source_id,
                enabled,
                database,
            ).model_dump()
        except Exception as exc:
            _raise_with_context(
                "set_signal_source_enabled",
                {"source_id": source_id, "enabled": enabled},
                exc,
            )

    def list_signal_sources(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> list[dict[str, Any]]:
        """Return public source configuration for Telegram display."""
        try:
            return [
                source.model_dump()
                for source in self.signal_intelligence_agent.list_sources(database)
            ]
        except Exception as exc:
            _raise_with_context("list_signal_sources", {}, exc)

    def get_signal_source(
        self,
        source_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Return one source record."""
        try:
            return self.signal_intelligence_agent.get_source(source_id, database).model_dump()
        except Exception as exc:
            _raise_with_context("get_signal_source", {"source_id": source_id}, exc)

    def scan_signal_source(
        self,
        source_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Manually scan one approved enabled source."""
        try:
            return self.signal_intelligence_agent.ingest_source(source_id, database)
        except Exception as exc:
            _raise_with_context("scan_signal_source", {"source_id": source_id}, exc)

    def scan_enabled_signal_sources(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Manually scan all approved enabled sources without scheduling."""
        try:
            return self.signal_intelligence_agent.ingest_enabled_sources(database)
        except Exception as exc:
            _raise_with_context("scan_enabled_signal_sources", {}, exc)

    def get_recent_signals(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent deterministic signals without Phase 8C ranking."""
        try:
            return self.signal_intelligence_agent.get_recent_signals(database, limit)
        except Exception as exc:
            _raise_with_context("get_recent_signals", {}, exc)

    def score_signal(
        self, signal_id: int, *, database: sqlite3.Connection | DatabaseRef
    ) -> dict[str, Any]:
        """Coordinate scoring of one stored signal; it never fetches a source."""
        try:
            result = self.signal_intelligence_agent.score_signal(signal_id, database)
            if result.get("eligible"):
                opportunity = self.signal_intelligence_agent.generate_content_opportunity(
                    signal_id, database
                )
                result["opportunity"] = (
                    None if opportunity is None else opportunity.model_dump()
                )
            return result
        except Exception as exc:
            _raise_with_context("score_signal", {"signal_id": signal_id}, exc)

    def score_recent_signals(
        self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 10, force: bool = False
    ) -> dict[str, Any]:
        """Coordinate a bounded stored-signal scoring run."""
        try:
            result = self.signal_intelligence_agent.score_recent_signals(database, limit, force)
            opportunities = self.signal_intelligence_agent.generate_top_content_opportunities(
                database, limit
            )
            result["opportunities_created"] = len(opportunities)
            return result
        except Exception as exc:
            _raise_with_context("score_recent_signals", {"limit": limit, "force": force}, exc)

    def get_scoring_queue(self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 10) -> list[dict[str, Any]]:
        """Preview the read-only, publication-first scoring selection queue."""
        try:
            return self.signal_intelligence_agent.get_scoring_queue(database, limit)
        except Exception as exc:
            _raise_with_context("get_scoring_queue", {"limit": limit}, exc)

    def generate_content_opportunity(
        self, signal_id: int, *, database: sqlite3.Connection | DatabaseRef
    ) -> dict[str, Any] | None:
        """Create a pre-draft opportunity only from a qualifying stored score."""
        try:
            result = self.signal_intelligence_agent.generate_content_opportunity(signal_id, database)
            return None if result is None else result.model_dump()
        except Exception as exc:
            _raise_with_context("generate_content_opportunity", {"signal_id": signal_id}, exc)

    def generate_top_content_opportunities(
        self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Create a bounded candidate batch without drafting any content post."""
        try:
            return [item.model_dump() for item in self.signal_intelligence_agent.generate_top_content_opportunities(database, limit)]
        except Exception as exc:
            _raise_with_context("generate_top_content_opportunities", {"limit": limit}, exc)

    def get_ranked_signals(
        self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return scored signals ordered for review."""
        try:
            return self.signal_intelligence_agent.list_ranked_signals(database, limit)
        except Exception as exc:
            _raise_with_context("get_ranked_signals", {"limit": limit}, exc)

    def get_scoring_diagnostics(self, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Expose read-only eligibility diagnostics for the operator interface."""
        try:
            return self.signal_intelligence_agent.get_scoring_diagnostics(database)
        except Exception as exc:
            _raise_with_context("get_scoring_diagnostics", {}, exc)

    def list_content_opportunities(
        self, *, database: sqlite3.Connection | DatabaseRef, status: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return content opportunities; they remain pre-draft records in Phase 8C."""
        try:
            return [item.model_dump() for item in self.signal_intelligence_agent.list_content_opportunities(database, status, limit)]
        except Exception as exc:
            _raise_with_context("list_content_opportunities", {"status": status}, exc)

    def get_content_opportunity(
        self, opportunity_id: int, *, database: sqlite3.Connection | DatabaseRef
    ) -> dict[str, Any]:
        """Return one reviewable opportunity."""
        try:
            return self.signal_intelligence_agent.get_content_opportunity(opportunity_id, database).model_dump()
        except Exception as exc:
            _raise_with_context("get_content_opportunity", {"opportunity_id": opportunity_id}, exc)

    def save_content_opportunity(self, opportunity_id: int, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Record an explicit human save decision."""
        return self._transition_content_opportunity(opportunity_id, "saved", database=database)

    def dismiss_content_opportunity(self, opportunity_id: int, reason: str | None = None, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Record an explicit human dismissal decision."""
        return self._transition_content_opportunity(opportunity_id, "dismissed", reason, database=database)

    def select_content_opportunity(self, opportunity_id: int, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Mark a future-drafting candidate without generating a post."""
        return self._transition_content_opportunity(opportunity_id, "selected", database=database)

    def record_signal_preference(self, signal_id: int, feedback_type: str, *, database: sqlite3.Connection | DatabaseRef, note: str | None = None) -> None:
        """Store user feedback only; no profile or weight mutation follows."""
        self._record_content_preference("signal", signal_id, feedback_type, database, note)

    def record_opportunity_preference(self, opportunity_id: int, feedback_type: str, *, database: sqlite3.Connection | DatabaseRef, note: str | None = None) -> None:
        """Store opportunity feedback only; no content drafting follows."""
        self._record_content_preference("opportunity", opportunity_id, feedback_type, database, note)

    def _transition_content_opportunity(self, opportunity_id: int, status: str, reason: str | None = None, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        try:
            return self.signal_intelligence_agent.transition_content_opportunity(opportunity_id, status, database, reason).model_dump()
        except Exception as exc:
            _raise_with_context("transition_content_opportunity", {"opportunity_id": opportunity_id, "status": status}, exc)

    def _record_content_preference(self, target_type: str, target_id: int, feedback_type: str, database: sqlite3.Connection | DatabaseRef, note: str | None) -> None:
        try:
            self.signal_intelligence_agent.record_preference(target_type, target_id, feedback_type, database, note)
        except Exception as exc:
            _raise_with_context("record_content_preference", {"target_type": target_type, "target_id": target_id}, exc)

    def get_signal(
        self,
        signal_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Return one attributed stored signal."""
        try:
            return self.signal_intelligence_agent.get_signal_by_id(signal_id, database)
        except Exception as exc:
            _raise_with_context("get_signal", {"signal_id": signal_id}, exc)

    def save_personal_brand_profile(
        self,
        profile: PersonalBrandProfileData | dict[str, Any],
        *,
        database: sqlite3.Connection | DatabaseRef,
        activate: bool = True,
    ) -> PersonalBrandProfile:
        """Append and optionally activate a validated personal-brand version."""
        try:
            return self.profile_context_agent.save_profile(
                profile=profile,
                database=database,
                activate=activate,
            )
        except Exception as exc:
            _raise_with_context("save_personal_brand_profile", {}, exc)

    def get_active_personal_brand_profile(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> PersonalBrandProfile | None:
        """Return the current active personal-brand profile version."""
        try:
            return self.profile_context_agent.get_active_profile(database)
        except Exception as exc:
            _raise_with_context("get_active_personal_brand_profile", {}, exc)

    def activate_personal_brand_profile(
        self,
        version: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> PersonalBrandProfile:
        """Activate an existing immutable personal-brand profile version."""
        try:
            return self.profile_context_agent.activate_profile(version, database)
        except Exception as exc:
            _raise_with_context(
                "activate_personal_brand_profile",
                {"version": version},
                exc,
            )

    def get_personal_brand_context(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> str:
        """Return deterministic prompt context for the active profile."""
        try:
            profile = self.profile_context_agent.get_active_profile(database)
            return (
                ""
                if profile is None
                else self.profile_context_agent.build_personal_brand_context(profile)
            )
        except Exception as exc:
            _raise_with_context("get_personal_brand_context", {}, exc)

    def get_active_brand_profile(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any] | None:
        """Return validated active profile data with version metadata."""
        try:
            profile = self.profile_context_agent.get_active_profile(database)
            if profile is None:
                return None
            return {
                "profile": profile,
                "data": self.profile_context_agent.validate_personal_brand_profile(
                    json.loads(profile.profile_json)
                ),
                "summary": self.profile_context_agent.summarize_personal_brand_profile(
                    profile
                ),
            }
        except Exception as exc:
            _raise_with_context("get_active_brand_profile", {}, exc)

    def get_brand_profile_summary(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any] | None:
        """Return concise active-profile fields for Telegram display."""
        try:
            profile = self.profile_context_agent.get_active_profile(database)
            return (
                None
                if profile is None
                else self.profile_context_agent.summarize_personal_brand_profile(profile)
            )
        except Exception as exc:
            _raise_with_context("get_brand_profile_summary", {}, exc)

    def list_brand_profile_versions(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent immutable profile-version summaries."""
        try:
            versions = self.profile_context_agent.list_profile_versions(database, limit)
            return [
                self.profile_context_agent.summarize_personal_brand_profile(profile)
                for profile in versions
            ]
        except Exception as exc:
            _raise_with_context("list_brand_profile_versions", {}, exc)

    def create_brand_profile_version(
        self,
        profile: PersonalBrandProfileData | dict[str, Any],
        *,
        database: sqlite3.Connection | DatabaseRef,
        activate: bool = True,
    ) -> dict[str, Any]:
        """Create a validated immutable profile version."""
        try:
            created = self.profile_context_agent.save_profile(
                profile,
                database,
                activate=activate,
            )
            return self.profile_context_agent.summarize_personal_brand_profile(created)
        except Exception as exc:
            _raise_with_context("create_brand_profile_version", {}, exc)

    def update_brand_profile_field(
        self,
        field_name: str,
        value: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Create and activate a new version from one safe field edit."""
        try:
            if field_name not in SUPPORTED_BRAND_PROFILE_FIELDS:
                allowed = ", ".join(sorted(SUPPORTED_BRAND_PROFILE_FIELDS))
                raise ValueError(f"Unsupported personal-brand field '{field_name}'. Allowed: {allowed}.")
            active = self.profile_context_agent.get_active_profile(database)
            if active is None:
                raise ValueError("No active personal-brand profile exists.")
            data = self.profile_context_agent.validate_personal_brand_profile(
                json.loads(active.profile_json)
            ).model_dump(mode="json")
            if field_name in BRAND_PROFILE_LIST_FIELDS:
                data[field_name] = [item.strip() for item in value.split(",") if item.strip()]
            else:
                data[field_name] = value.strip() or None
            validated = self.profile_context_agent.validate_personal_brand_profile(data)
            created = self.profile_context_agent.save_profile(
                validated,
                database,
                activate=True,
            )
            return self.profile_context_agent.summarize_personal_brand_profile(created)
        except Exception as exc:
            _raise_with_context(
                "update_brand_profile_field",
                {"field_name": field_name},
                exc,
            )

    def activate_brand_profile(
        self,
        version: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Activate a validated historical profile version by version number."""
        try:
            profile = self.profile_context_agent.get_profile(version, database)
            self.profile_context_agent.validate_personal_brand_profile(
                json.loads(profile.profile_json)
            )
            active = self.profile_context_agent.activate_profile(version, database)
            return self.profile_context_agent.summarize_personal_brand_profile(active)
        except Exception as exc:
            _raise_with_context("activate_brand_profile", {"version": version}, exc)

    def get_pending_drafts(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return pending outreach and content drafts for Telegram display."""
        try:
            connection, should_close = _coerce_connection(database)
            try:
                outreach_rows = connection.execute(
                    """
                    SELECT
                        interactions.id,
                        interactions.prospect_id,
                        interactions.interaction_type,
                        interactions.content,
                        interactions.status,
                        interactions.source,
                        interactions.created_at,
                        prospects.name AS prospect_name
                    FROM interactions
                    JOIN prospects ON prospects.id = interactions.prospect_id
                    WHERE interactions.interaction_type IN (
                        'outreach_draft',
                        'follow_up_draft'
                    )
                        AND interactions.status = 'drafted'
                    ORDER BY interactions.created_at ASC, interactions.id ASC
                    """
                ).fetchall()
                content_rows = connection.execute(
                    """
                    SELECT *
                    FROM content_posts
                    WHERE status IN (
                        'draft',
                        'saved',
                        'approved_for_later_posting'
                    )
                    ORDER BY created_at ASC, id ASC
                    """
                ).fetchall()
            finally:
                if should_close:
                    connection.close()
            return {
                "outreach": [_format_pending_outreach(row) for row in outreach_rows],
                "content": [_format_pending_content(row) for row in content_rows],
            }
        except Exception as exc:
            _raise_with_context("get_pending_drafts", {}, exc)

    def build_daily_briefing(self, *, database: sqlite3.Connection | DatabaseRef, run_type: str = "manual", dry_run: bool = False) -> dict[str, Any]:
        """Build one idempotent proactive briefing without any LinkedIn action."""
        try:
            connection, should_close = _coerce_connection(database)
            try:
                settings_row = connection.execute("SELECT * FROM briefing_settings WHERE id = 1").fetchone()
                now = datetime.now(UTC)
                timezone = settings_row["timezone"] if settings_row else "America/New_York"
                run_key = hashlib.sha256(f"{run_type}:{timezone}:{now.date().isoformat()}:{now.hour}".encode()).hexdigest()[:32]
                existing = connection.execute("SELECT * FROM briefing_runs WHERE run_key = ?", (run_key,)).fetchone()
                if existing is not None:
                    return {"run_id": existing["id"], "status": "skipped", "run_key": run_key, "reason": "Briefing window already ran."}
                cursor = connection.execute("INSERT INTO briefing_runs (run_key, run_type, scheduled_for, timezone, started_at, status, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, 'started', ?, ?)", (run_key, run_type, now.isoformat(), timezone, now.isoformat(), now.isoformat(), json.dumps({"dry_run": dry_run})))
                run_id = cursor.lastrowid
                connection.commit()
            finally:
                if should_close:
                    connection.close()
            scan = self.scan_enabled_signal_sources(database=database)
            scored = self.score_recent_signals(limit=10, database=database)
            packages: list[dict[str, Any]] = []
            for opportunity in self.list_content_opportunities(database=database, status="candidate", limit=1):
                try:
                    packages.append(self.generate_content_package(opportunity["id"], database=database))
                except NetworkOrchestratorError:
                    continue
            followups = self.get_followups_due(database=cast(DatabaseRef, database))
            connection, should_close = _coerce_connection(database)
            try:
                completed = datetime.now(UTC).isoformat()
                status = "completed" if packages or followups or scored.get("scored", 0) else "no_content"
                connection.execute("UPDATE briefing_runs SET completed_at = ?, status = ?, sources_considered_count = ?, sources_succeeded_count = ?, sources_failed_count = ?, new_signals_count = ?, duplicate_signals_count = ?, signals_scored_count = ?, eligible_signals_count = ?, opportunities_created_count = ?, packages_prepared_count = ?, followups_due_count = ?, metadata_json = ? WHERE id = ?", (completed, status, scan.get("sources_scanned", 0), scan.get("sources_scanned", 0) - scan.get("failures", 0), scan.get("failures", 0), scan.get("new_signals", 0), scan.get("duplicates", 0), scored.get("scored", 0), scored.get("eligible", 0), scored.get("opportunities_created", 0), len(packages), len(followups), json.dumps({"dry_run": dry_run, "packages": [item.get("id") for item in packages]}), run_id))
                connection.commit()
            finally:
                if should_close:
                    connection.close()
            return {"run_id": run_id, "run_key": run_key, "status": status, "scan": scan, "scoring": scored, "packages": packages, "followups": followups, "dry_run": dry_run}
        except Exception as exc:
            _raise_with_context("build_daily_briefing", {"run_type": run_type}, exc)

    def list_briefing_runs(self, *, database: sqlite3.Connection | DatabaseRef, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent auditable briefing summaries."""
        connection, should_close = _coerce_connection(database)
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM briefing_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        finally:
            if should_close:
                connection.close()

    def get_briefing_status(self, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Return safe operational briefing state for Telegram display."""
        connection, should_close = _coerce_connection(database)
        try:
            config = connection.execute("SELECT * FROM briefing_settings WHERE id = 1").fetchone()
            last_run = connection.execute("SELECT * FROM briefing_runs ORDER BY id DESC LIMIT 1").fetchone()
            if config is None:
                raise ValueError("Briefing settings have not been initialized.")
            return {"enabled": bool(config["enabled"]), "briefing_time": config["briefing_time"], "timezone": config["timezone"], "dry_run": bool(config["dry_run"]), "last_run": None if last_run is None else dict(last_run)}
        except Exception as exc:
            _raise_with_context("get_briefing_status", {}, exc)
        finally:
            if should_close:
                connection.close()

    def update_briefing_settings(self, *, enabled: bool | None = None, briefing_time: str | None = None, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Persist a limited operational setting without starting any scheduler."""
        if briefing_time is not None:
            try:
                datetime.strptime(briefing_time, "%H:%M")
            except ValueError as exc:
                raise NetworkOrchestratorError("Briefing time must use HH:MM.") from exc
        connection, should_close = _coerce_connection(database)
        try:
            existing = self.get_briefing_status(database=connection)
            connection.execute("UPDATE briefing_settings SET enabled = ?, briefing_time = ?, updated_at = ? WHERE id = 1", (int(existing["enabled"] if enabled is None else enabled), existing["briefing_time"] if briefing_time is None else briefing_time, datetime.now(UTC).isoformat()))
            connection.commit()
            return self.get_briefing_status(database=connection)
        except Exception as exc:
            _raise_with_context("update_briefing_settings", {}, exc)
        finally:
            if should_close:
                connection.close()

    def save_content_draft(
        self,
        post_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Mark an internally generated content draft as saved."""
        return self._update_content_post_status(
            post_id,
            "saved",
            database=database,
            method_name="save_content_draft",
        )

    def generate_content_package(self, opportunity_id: int, *, database: sqlite3.Connection | DatabaseRef, image_mode: str = "disabled") -> dict[str, Any]:
        """Prepare a review-only package from a stored opportunity; never publish it."""
        try:
            return self.content_inspiration_agent.generate_package_from_opportunity(
                opportunity_id, database, image_mode
            ).model_dump()
        except Exception as exc:
            _raise_with_context("generate_content_package", {"opportunity_id": opportunity_id}, exc)

    def get_content_package(self, post_id: int, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Load one package-backed draft for Telegram review."""
        try:
            return self.content_inspiration_agent.get_package(post_id, database).model_dump()
        except Exception as exc:
            _raise_with_context("get_content_package", {"post_id": post_id}, exc)

    def list_pending_content_packages(self, *, database: sqlite3.Connection | DatabaseRef) -> list[dict[str, Any]]:
        """List existing package drafts without making a post."""
        try:
            return [post.model_dump() for post in self.content_inspiration_agent.get_pending_drafts(database) if post.package_json]
        except Exception as exc:
            _raise_with_context("list_pending_content_packages", {}, exc)

    def approve_content_package_for_later(self, post_id: int, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Approve internally only after deterministic package validation."""
        try:
            post = self.content_inspiration_agent.get_package(post_id, database)
            blockers = self.content_inspiration_agent.validate_package_for_approval(post)
            if blockers:
                raise ValueError("; ".join(blockers))
            result = self._update_content_post_status(post_id, "approved_for_later_posting", database=database, method_name="approve_content_package_for_later")
            return {**result, "message": "Approved for later posting. Nothing has been published."}
        except Exception as exc:
            _raise_with_context("approve_content_package_for_later", {"post_id": post_id}, exc)

    def reject_content_package(self, post_id: int, reason: str | None = None, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Reject a package without touching LinkedIn or its source opportunity."""
        _ = reason
        return self._update_content_post_status(post_id, "discarded", database=database, method_name="reject_content_package")

    def revise_content_package(self, post_id: int, revision_type: str, *, database: sqlite3.Connection | DatabaseRef) -> dict[str, Any]:
        """Run a controlled revision that preserves package provenance."""
        try:
            return self.content_inspiration_agent.revise_package(post_id, revision_type, database).model_dump()
        except Exception as exc:
            _raise_with_context("revise_content_package", {"post_id": post_id, "revision_type": revision_type}, exc)

    def approve_content_draft_for_later_posting(
        self,
        post_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Mark a content draft approved internally without publishing."""
        return self._update_content_post_status(
            post_id,
            "approved_for_later_posting",
            database=database,
            method_name="approve_content_draft_for_later_posting",
        )

    def discard_content_draft(
        self,
        post_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Discard an internal content draft without external action."""
        return self._update_content_post_status(
            post_id,
            "discarded",
            database=database,
            method_name="discard_content_draft",
        )

    def record_outreach_outcome(
        self,
        prospect_id: int,
        replied: bool,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> None:
        """Record an outreach reply outcome for refinement.

        MVP simplification: interactions do not yet store the parameter
        version active at draft time, so this uses the currently active
        outreach parameter version when the outcome is recorded.
        """
        try:
            _ = prospect_id
            active_version = _current_active_version(
                database=database,
                agent_name="outreach_draft_agent",
            )
            self.refinement_loop_agent.record_outcome(
                agent_name="outreach_draft_agent",
                parameter_version=active_version,
                metric_value=1.0 if replied else 0.0,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "record_outreach_outcome",
                {"prospect_id": prospect_id, "replied": replied},
                exc,
            )

    def run_refinement_cycle(
        self,
        agent_name: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Ask RefinementLoopAgent to propose the next controlled refinement."""
        try:
            return self.refinement_loop_agent.propose_refinement(
                agent_name=agent_name,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "run_refinement_cycle",
                {"agent_name": agent_name},
                exc,
            )

    def record_outcome(
        self,
        target_type: str,
        target_id: int,
        outcome: str,
        notes: str | None = None,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Record an explicit user-reported refinement outcome."""
        try:
            return self.refinement_loop_agent.record_explicit_outcome(
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                notes=notes,
                database=database,
                source="telegram_command",
            )
        except Exception as exc:
            _raise_with_context(
                "record_outcome",
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "outcome": outcome,
                },
                exc,
            )

    def suggest_refinements(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Run the Phase 6A report-only refinement loop."""
        try:
            return self.refinement_loop_agent.run_report_only_refinement_loop(
                database=database,
            )
        except Exception as exc:
            _raise_with_context("suggest_refinements", {}, exc)

    def apply_refinement(
        self,
        proposal: dict[str, Any],
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Apply a human-approved refinement after core-intent validation."""
        try:
            return self.refinement_loop_agent.accept_refinement(
                {**proposal, "source": "telegram_callback"},
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "apply_refinement",
                {"agent_name": proposal.get("agent_name")},
                exc,
            )

    def apply_refinement_proposal(
        self,
        proposal_id: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Apply a persisted human-approved refinement proposal."""
        try:
            return self.refinement_loop_agent.apply_persisted_proposal(
                proposal_id=proposal_id,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "apply_refinement_proposal",
                {"proposal_id": proposal_id},
                exc,
            )

    def reject_refinement(
        self,
        proposal: dict[str, Any],
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Record a human rejection without changing parameters."""
        try:
            _ = database
            return {
                "status": "rejected",
                "agent_name": proposal.get("agent_name"),
            }
        except Exception as exc:
            _raise_with_context(
                "reject_refinement",
                {"agent_name": proposal.get("agent_name")},
                exc,
            )

    def reject_refinement_proposal(
        self,
        proposal_id: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Reject a persisted refinement proposal without changing parameters."""
        try:
            return self.refinement_loop_agent.reject_persisted_proposal(
                proposal_id=proposal_id,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "reject_refinement_proposal",
                {"proposal_id": proposal_id},
                exc,
            )

    def get_refinement_reasoning(
        self,
        proposal_id: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Return user-facing reasoning for a persisted proposal."""
        try:
            return self.refinement_loop_agent.get_persisted_proposal_reasoning(
                proposal_id=proposal_id,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "get_refinement_reasoning",
                {"proposal_id": proposal_id},
                exc,
            )

    def rollback_refinement(
        self,
        refinement_id: int,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Rollback one applied refinement event by refinement_history id."""
        try:
            return self.refinement_loop_agent.rollback_applied_refinement(
                refinement_id=refinement_id,
                database=database,
            )
        except Exception as exc:
            _raise_with_context(
                "rollback_refinement",
                {"refinement_id": refinement_id},
                exc,
            )

    def get_refinement_history(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent refinement history events for Telegram display."""
        try:
            return self.refinement_loop_agent.recent_refinement_history(
                database=database,
                limit=limit,
            )
        except Exception as exc:
            _raise_with_context("get_refinement_history", {"limit": limit}, exc)

    def get_refinement_status(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Return read-only refinement loop status for Telegram."""
        try:
            return self.refinement_loop_agent.get_refinement_status(database=database)
        except Exception as exc:
            _raise_with_context("get_refinement_status", {}, exc)

    def get_refinement_report(
        self,
        *,
        database: sqlite3.Connection | DatabaseRef,
    ) -> dict[str, Any]:
        """Return a read-only refinement report for Telegram."""
        try:
            return self.refinement_loop_agent.get_refinement_report(database=database)
        except Exception as exc:
            _raise_with_context("get_refinement_report", {}, exc)

    def _tracker(self, database: DatabaseRef) -> Any:
        return self.tracker_factory(database)

    def _update_content_post_status(
        self,
        post_id: int,
        status: str,
        *,
        database: sqlite3.Connection | DatabaseRef,
        method_name: str,
    ) -> dict[str, Any]:
        try:
            connection, should_close = _coerce_connection(database)
            try:
                row = connection.execute(
                    "SELECT id FROM content_posts WHERE id = ?",
                    (post_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Content draft id {post_id} does not exist.")
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    """
                    UPDATE content_posts
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, post_id),
                )
                connection.commit()
            finally:
                if should_close:
                    connection.close()
            return {"post_id": post_id, "status": status}
        except Exception as exc:
            _raise_with_context(method_name, {"post_id": post_id}, exc)


def _format_due_followup(prospect: Prospect) -> dict[str, Any]:
    return {
        "prospect_id": prospect.id,
        "name": prospect.name,
        "role_title": prospect.role_title,
        "company": prospect.company,
        "last_touch_date": prospect.last_touch_date,
        "status": prospect.status,
    }


def _format_pending_outreach(row: sqlite3.Row) -> dict[str, Any]:
    content = _json_object(row["content"])
    return {
        "type": "outreach",
        "id": row["id"],
        "prospect_id": row["prospect_id"],
        "prospect_name": row["prospect_name"],
        "interaction_type": row["interaction_type"],
        "ask_type": content.get("ask_type"),
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _format_pending_content(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "type": "content",
        "id": row["id"],
        "topic": row["topic"],
        "image_source": row["image_source"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _json_object(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, str) or not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _current_active_version(
    database: sqlite3.Connection | DatabaseRef,
    agent_name: str,
) -> int:
    connection, should_close = _coerce_connection(database)
    try:
        row = connection.execute(
            """
            SELECT version
            FROM refinable_parameters
            WHERE agent_name = ? AND is_active = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (agent_name,),
        ).fetchone()
        if row is None:
            return 1
        return int(row["version"])
    finally:
        if should_close:
            connection.close()


def _coerce_connection(
    database: sqlite3.Connection | DatabaseRef,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        return database, False
    return connect(database), True


def _raise_with_context(
    method_name: str,
    context: dict[str, Any],
    exc: Exception,
) -> NoReturn:
    if isinstance(exc, NetworkOrchestratorError):
        raise exc
    context_text = ", ".join(f"{key}={value!r}" for key, value in context.items())
    if context_text:
        message = f"{method_name} failed ({context_text}): {exc}"
    else:
        message = f"{method_name} failed: {exc}"
    raise NetworkOrchestratorError(message) from exc
