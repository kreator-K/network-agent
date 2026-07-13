# LinkedIn Token Security

Access and optional refresh tokens are Fernet-encrypted before storage. The
encryption key is supplied by `LINKEDIN_TOKEN_ENCRYPTION_KEY` and is never
stored in SQLite or displayed by Telegram. SQLite stores encrypted blobs,
validated OIDC subject, granted scopes, expiry, status, and timestamps.

Authorization codes, raw OAuth state, client secrets, and raw ID tokens are
not persisted. A successful OAuth flow does not enable publishing.
