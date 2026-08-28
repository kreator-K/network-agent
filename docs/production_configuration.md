# Production Configuration

Runtime loads only `.env.local`. Required deployment values include an
authenticated web API token/session configuration, absolute database and
storage paths, stable HTTPS callback URI, LinkedIn OAuth values, encrypted-token
key, Calendar MCP paths/account, and model/image settings. Telegram values are
migration-only and are not required for web deployment. Diagnostics report only configured,
missing, valid, invalid, and selected modes.

Safe initial values:

```env
APPLICATION_ENVIRONMENT=production
LINKEDIN_PUBLISH_MODE=disabled
LINKEDIN_REAL_PUBLISH_ENABLED=false
IMAGE_MODE=disabled
DAILY_BRIEFING_ENABLED=false
PUBLIC_SIGNAL_ALLOW_HTTP=false
```

Changing environment values requires a controlled restart. Never put
`.env.local`, credentials, tokens, or keys in an image or Git commit.
