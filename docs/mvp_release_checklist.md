# MVP Release Checklist

- [ ] Python 3.11 virtual environment is active.
- [ ] `.env.local` contains the Telegram token and, for real model mode, Nvidia API key.
- [ ] `.env.local`, provider credentials, and token files are ignored by Git.
- [ ] `DATABASE_PATH` points to the intended SQLite database.
- [ ] `.venv/bin/python scripts/init_db.py` completed successfully.
- [ ] Fresh-database `/system_check` reports all checks passed.
- [ ] `/start`, `/add_prospect`, `/draft_outreach`, and manual-send callback tested.
- [ ] `/followups_due` and `/draft_followup` tested against a saved interaction.
- [ ] `/meeting_confirmed` tested with valid and invalid date/time values.
- [ ] `/draft_post` and `/pending_drafts` tested.
- [ ] `/record_outcome`, `/suggest_refinements`, `/refinement_status`, `/refinement_report`, and `/refinement_history` tested.
- [ ] No message says the bot sent LinkedIn outreach or published content.
- [ ] No provider API key appears in logs or error messages.
- [ ] `.venv/bin/python -m pytest -v`, `.venv/bin/python -m mypy .`, and `.venv/bin/python -m ruff check .` are clean.

## Known Non-MVP Features

LinkedIn OAuth, automatic connection requests or messages, LinkedIn scraping, automatic posting, Google Calendar OAuth, email invitations, freeform meeting detection, and unattended refinements are out of scope.
