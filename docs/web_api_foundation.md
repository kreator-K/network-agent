# Web API Foundation

The ASGI API in `api/app.py` is the authenticated product boundary for the new
web interface. Routes validate input and call `NetworkOrchestrator`; they never
call specialist agents, model providers, or LinkedIn clients directly.

## Authentication

The first foundation uses one owner bearer token from `WEB_API_TOKEN`. Missing
configuration fails closed with HTTP 503, and invalid credentials return a
generic HTTP 401 envelope. This is a temporary private-beta boundary. Browser
sessions, CSRF protection, token rotation, and a durable web-user identity must
replace it before public deployment.

## Routes

- `GET /healthz`
- `GET /api/v1/diagnostics`
- `GET /api/v1/signals`
- `POST /api/v1/signals/scan`
- `GET /api/v1/opportunities`
- `POST /api/v1/opportunities/{id}/content-package`
- `GET /api/v1/content/{id}`

All protected responses use `{ "data": ... }`. Errors use a generic code,
message, and request ID. Internal exception text and credentials are not
returned.

The content-generation route only creates a draft package. Publishing and
calendar mutation routes are intentionally absent until web session ownership
and dedicated confirmation contracts exist.
