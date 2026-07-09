"""Google Calendar integration boundary.

Real Google Calendar OAuth/API integration is Phase 4 scope. Implementing it
will require OAuth credentials, calendar ID configuration, token storage, and
provider error handling. Phase 1 supports mock event IDs only.
"""


def block_time(
    meeting_date: str,
    start_time: str,
    end_time: str | None,
    timezone: str | None,
    title: str,
    mock_mode: bool,
) -> str:
    """Block calendar time or return a deterministic mock event ID.

    Mock mode does not call any real API. Real mode raises because Google
    Calendar OAuth/API integration is Phase 4 scope.
    """
    if mock_mode:
        safe_date = meeting_date.replace("-", "")
        safe_time = start_time.replace(":", "")
        return f"mock-calendar-event-{safe_date}-{safe_time}"
    raise NotImplementedError(
        "Real Google Calendar sync is Phase 4 scope and requires OAuth "
        "credentials, calendar ID configuration, and token storage."
    )
