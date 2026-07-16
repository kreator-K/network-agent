# Incident Response

1. Disable the relevant feature in `.env.local` and restart the process.
2. Preserve the database and collect redacted logs; do not copy secrets.
3. Run `/system_check`, `/linkedin_publish_diagnostics`, and the relevant
   status command.
4. Inspect durable records before retrying. Uncertain LinkedIn requests require
   manual provider inspection and controlled resolution. Calendar retries must
   reuse the existing idempotency key.
5. If a database is suspected, create a SQLite backup and investigate a copy.
6. Record the safe error code, stage, timestamp, and internal entity ID in the
   incident report.

Never retry an uncertain LinkedIn write automatically, never treat a failed
Telegram response as proof that no provider write occurred, and never expose
OAuth credentials or raw provider responses.
