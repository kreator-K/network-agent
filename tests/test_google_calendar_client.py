"""Tests for the Google Calendar integration boundary."""

import pytest

from integrations.google_calendar_client import block_time


def test_block_time_mock_mode_returns_event_id_without_real_call() -> None:
    result = block_time(
        meeting_date="2026-01-20",
        start_time="09:30",
        end_time="10:00",
        timezone="UTC",
        title="Networking",
        mock_mode=True,
    )

    assert result == "mock-calendar-event-20260120-0930"


def test_block_time_real_mode_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 4"):
        block_time(
            meeting_date="2026-01-20",
            start_time="09:30",
            end_time="10:00",
            timezone="UTC",
            title="Networking",
            mock_mode=False,
        )
