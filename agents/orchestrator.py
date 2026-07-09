"""Application orchestration layer for Network Growth Agent workflows."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, cast

from agents.calendar_agent import CalendarAgent
from agents.content_inspiration_agent import ContentInspirationAgent
from agents.outreach_draft_agent import AskType, OutreachDraftAgent
from agents.profile_context_agent import ProfileContextAgent
from agents.prospect_discovery_agent import ProspectDiscoveryAgent
from agents.refinement_loop_agent import RefinementLoopAgent
from agents.relationship_tracker_agent import RelationshipTrackerAgent
from db.database import connect
from db.models import ContentPost, Prospect


DatabaseRef = str | Path
TrackerFactory = Callable[[DatabaseRef], Any]


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
            tracker.log_interaction(
                prospect_id=prospect_id,
                interaction_type="outreach_draft",
                content=str(draft.get("draft_text", "")),
                direction="outbound_draft",
            )
            return {"draft": draft, "context_warning": context_warning}
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
            tracker.log_interaction(
                prospect_id=prospect_id,
                interaction_type="follow_up_draft",
                content=str(draft.get("draft_text", "")),
                direction="outbound_draft",
            )
            return {"draft": draft}
        except Exception as exc:
            _raise_with_context("draft_followup", {"prospect_id": prospect_id}, exc)

    def mark_outreach_sent(
        self,
        prospect_id: int,
        *,
        database: DatabaseRef,
    ) -> dict[str, Prospect | str]:
        """Mark manually sent outreach after explicit Telegram approval."""
        try:
            tracker = self._tracker(database)
            prospect = tracker.update_status(prospect_id, "connection_sent")
            return {"prospect": prospect, "status": "connection_sent"}
        except Exception as exc:
            _raise_with_context(
                "mark_outreach_sent",
                {"prospect_id": prospect_id},
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

    def _tracker(self, database: DatabaseRef) -> Any:
        return self.tracker_factory(database)


def _format_due_followup(prospect: Prospect) -> dict[str, Any]:
    return {
        "prospect_id": prospect.id,
        "name": prospect.name,
        "role_title": prospect.role_title,
        "company": prospect.company,
        "last_touch_date": prospect.last_touch_date,
        "status": prospect.status,
    }


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
