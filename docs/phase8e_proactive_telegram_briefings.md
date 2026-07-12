# Phase 8E: Proactive Telegram Briefings

`scripts/run_daily_briefing.py` is an idempotent operational runner, not a daemon or agent. Invoke it through cron, launchd, or a systemd timer with the project virtual environment and working directory. It creates a unique run record, scans only approved enabled sources, scores bounded stored signals, prepares at most one review package, and records follow-ups.

Use `--dry-run` for safe execution without delivery. Use `--force` for a manual run when daily briefing is disabled. Scheduling configuration remains operational: do not put secrets in a cron line; load the existing environment file instead. No run publishes, approves packages, sends outreach, scrapes LinkedIn, or modifies profiles and scoring weights.
