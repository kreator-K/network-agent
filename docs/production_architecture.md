# Production Architecture

```text
stable HTTPS reverse proxy (TLS)
        -> callback service (/v1/callback, /healthz, /readyz)
Telegram -> one Network Agent bot process -> SQLite persistent volume
                                      -> Google Calendar MCP Node child
one systemd backup timer ----------------> encrypted SQLite backup directory
```

Run one writable application instance and one scheduler owner. The callback
service and bot must load the same project-root `.env.local` and absolute
`DATABASE_PATH`. `.env.example` is never loaded at runtime. Secrets stay
outside release artifacts, and all provider writes remain behind approval
boundaries.
