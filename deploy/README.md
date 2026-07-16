# Systemd Deployment Target

Phase 10 supports one Linux VM with a dedicated non-root `network-agent`
service account, one writable SQLite instance, one Telegram bot, one callback
adapter, one Google Calendar MCP subprocess owned by the bot, and one backup
timer. A reverse proxy terminates TLS and forwards only `/v1/callback`,
`/healthz`, and `/readyz` to the callback service.

Install the repository at an absolute path, keep `.env.local` outside the Git
release artifact, and set `TELEGRAM_ALLOWED_USER_IDS` and
`TELEGRAM_ADMIN_USER_IDS` to deliberate numeric IDs before starting. The unit
files use `/opt/network-agent` as the deployment path and must be reviewed for
the target host before installation.

```bash
python scripts/prepare_runtime.py
python scripts/pre_deploy.py
sudo systemctl enable --now network-agent-bot.service network-agent-callback.service network-agent-backup.timer
curl -fsS https://beta.example.com/healthz
curl -fsS https://beta.example.com/readyz
```

Do not expose the callback directly to the Internet without a managed HTTPS
reverse proxy. Do not run more than one writable bot or scheduler against the
same SQLite database.
