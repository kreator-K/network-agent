# Production Architecture

```text
Vercel Next.js UI (stable HTTPS)
        -> authenticated Python 3.11 API
        -> SQLite persistent volume
        -> Google Calendar MCP Node child
one reviewed backup process ----------------> encrypted SQLite backup directory
```

Run one writable API instance and one scheduler owner. The Vercel UI uses a
server-only API token and owner session secret; the API loads the same absolute
`DATABASE_PATH` and Python 3.11 environment. `.env.example` is never loaded at
runtime. Secrets stay outside release artifacts, and all provider writes remain
behind approval boundaries. Telegram and the former systemd unit are
migration-only.
