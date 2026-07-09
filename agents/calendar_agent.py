"""Calendar coordination agent."""

from typing import Any


class CalendarAgent:
    """Prepare calendar blocks after explicit meeting confirmation.

    Purpose:
        Block calendar time only after the user sends an explicit
        `/meeting_confirmed` command.
    Inputs:
        Confirmed meeting command payload, prospect record, date, time,
        duration, timezone, and meeting context.
    Outputs:
        Calendar block requests or validation errors.
    """

    def prepare_block(self, meeting: dict[str, Any]) -> dict[str, Any]:
        """Return a mock calendar block request."""
        return {"mock": True, "meeting": meeting}
