# LinkedIn OAuth Setup

Phase 8G-B1 uses LinkedIn's official authorization-code OAuth and OIDC
userinfo endpoints directly. LinkedIn MCP, scraping, messaging, connection
requests, InMail, feed reads, and publishing are out of scope.

Required environment variables are `LINKEDIN_CLIENT_ID`,
`LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REDIRECT_URI` (an exact HTTPS callback),
`LINKEDIN_OAUTH_SCOPES=openid profile w_member_social`,
`LINKEDIN_TOKEN_ENCRYPTION_KEY` (a Fernet key stored outside SQLite),
`LINKEDIN_TOKEN_PATH`, `LINKEDIN_OAUTH_STATE_TTL_SECONDS`,
`LINKEDIN_REQUEST_TIMEOUT_SECONDS`, and `LINKEDIN_PUBLISH_MODE=disabled`.

In the LinkedIn Developer Portal, create an application, configure the exact
HTTPS redirect URI, and request only the three allowlisted scopes. Approval of
`w_member_social` does not enable posting in this phase.

Run the callback adapter with `.venv/bin/python scripts/run_linkedin_callback.py`
behind an HTTPS reverse proxy, and run the Telegram bot separately with
`.venv/bin/python scripts/run_bot.py`. The callback stores only encrypted
tokens and minimal validated OIDC identity. Browser errors are intentionally
generic.
