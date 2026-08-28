"""Run the ASGI API on the provider-assigned port."""

from __future__ import annotations

import os

import uvicorn


def api_port(raw_value: str | None = None) -> int:
    """Return a valid provider port, defaulting to the local container port."""
    value = raw_value if raw_value is not None else os.getenv("PORT", "8000")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PORT must be an integer between 1 and 65535.") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("PORT must be an integer between 1 and 65535.")
    return port


def main() -> None:
    """Start one API process; SQLite deployments must remain single-instance."""
    uvicorn.run("api.index:app", host="0.0.0.0", port=api_port())


if __name__ == "__main__":
    main()
