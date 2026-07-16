# Release Candidate Checklist

- [ ] Confirm branch is `main` and unrelated worktree files are preserved.
- [ ] Confirm `.env.local` is ignored and `.env.example` is not loaded.
- [ ] Run `python -m scripts.release_check`.
- [ ] Review configuration diagnostics without printing values.
- [ ] Verify temporary-copy migration and `/system_check` pass.
- [ ] Verify `LINKEDIN_PUBLISH_MODE=disabled` and the real-write switch is false.
- [ ] Verify no real LinkedIn write, media upload, outreach, or unconfirmed calendar change occurred.
- [ ] Run `python -m pytest`, `python -m mypy .`, and `python -m ruff check .`.
- [ ] Start with `python -m scripts.run_bot` and verify safe startup logs.
- [ ] Stop with Ctrl+C and verify Calendar MCP shutdown and no orphan process.
- [ ] Back up SQLite before any operational migration or restore.
- [ ] Review `docs/operator_runbook.md` and collect only redacted logs.
- [ ] Commit only reviewed source, tests, and documentation.
