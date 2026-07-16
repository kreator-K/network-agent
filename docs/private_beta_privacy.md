# Private Beta Privacy

SQLite is the source of truth and remains on the private deployment volume.
Feedback stores only the authorized numeric Telegram ID, category, message,
and timestamp. Metrics exclude full messages, post text, tokens, and
unnecessary personal attributes. Restrict database, media, log, state, and
backup directories to the service account and define retention before adding
beta users.
