# Deployment Runbook

1. Install Python 3.11, Node, the repository, and a dedicated non-root
   `network-agent` account on one Linux VM.
2. Place `.env.local` outside the release artifact. Set numeric
   `TELEGRAM_ALLOWED_USER_IDS` and `TELEGRAM_ADMIN_USER_IDS`; use a stable
   HTTPS `LINKEDIN_REDIRECT_URI` ending in `/v1/callback`.
3. Run `python scripts/prepare_runtime.py` and
   `python scripts/pre_deploy.py`.
4. Create and verify a timestamped SQLite backup before stopping the old
   process. Stop the bot, apply migrations, then start the bot and callback
   systemd units.
5. Check `/healthz`, `/readyz`, `/system_check`, LinkedIn status, and Calendar
   status. Confirm publishing is disabled and scheduled jobs are off.
6. Run only local/disabled smoke tests. Record the release version and backup.

Rollback: stop the failed units, preserve logs, restore the prior application
release, and restore the database only when required by the migration plan.
Never automatically retry an uncertain provider write.
