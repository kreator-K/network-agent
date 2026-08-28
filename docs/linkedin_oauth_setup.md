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

The products are separate: **Sign In with LinkedIn using OpenID Connect**
supplies `openid` and `profile`, while **Share on LinkedIn** supplies
`w_member_social`. Confirm the app's Auth tab lists all three permissions.
Seeing a scope in the generated authorization URL proves only that it was
requested; the callback accepts only permissions actually granted in the token
response or verified by LinkedIn token introspection.

Set the registered callback to the Vercel frontend's stable HTTPS
`/linkedin/callback` route. That server route forwards the allowlisted callback
parameters to the bearer-protected Python API, where the orchestrator validates
the one-time OAuth state and stores only encrypted tokens plus minimal validated
OIDC identity. Browser errors are intentionally generic. The former standalone
callback and Telegram runners are migration-only.
