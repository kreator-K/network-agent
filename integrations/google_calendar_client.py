"""Google Calendar integration stub."""

from typing import Any


class GoogleCalendarClient:
    """Prepare future Google Calendar API calls in mock mode.

    Purpose:
        Represent the calendar-provider boundary without making real API calls.
    Inputs:
        Calendar block payloads from CalendarAgent after `/meeting_confirmed`.
    Outputs:
        Mock calendar operation results.
    """

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a mock calendar event result."""
        return {"mock": True, "created": False, "payload": payload}
