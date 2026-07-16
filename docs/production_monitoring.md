# Production Monitoring

Monitor `/healthz` for liveness and `/readyz` for local readiness. Collect
structured safe logs for startup, shutdown, workflow name, request ID, stage,
duration, typed errors, scheduler runs, backup status, uncertainty, and
unauthorized access attempts. Rotate logs and monitor disk usage. Do not log
tokens, OAuth codes/state, authorization headers, upload URLs, full private
Telegram messages, or unnecessary prospect biography.
