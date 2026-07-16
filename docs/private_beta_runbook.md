# Private Beta Runbook

Start owner-only. Before admitting another user, add their numeric Telegram
ID deliberately, explain that outreach is never sent automatically, and
explain that a LinkedIn post becomes public only after final confirmation.

Owner checklist: verify `/healthz`, `/readyz`, `/system_check`,
`/linkedin_connection_status`, `/linkedin_publish_status`, Calendar status,
backup creation, and safe logs. Keep `LINKEDIN_PUBLISH_MODE=disabled` and
`LINKEDIN_REAL_PUBLISH_ENABLED=false` during normal beta operation.

Use `/feedback <message>` for local feedback and `/beta_status` for an
admin-only summary. Revoke access by removing the numeric ID and restarting
the bot. Do not add users by display name or username.
