# Production Incident Response

For token, client-secret, encryption-key, Telegram-token, database, callback,
Calendar, MCP, disk, or unexpected-publication incidents: stop affected
services, disable the affected feature, preserve redacted logs, rotate or
revoke credentials as appropriate, identify the exposure path, verify Git and
artifacts, and restore only after checks pass. For uncertain LinkedIn writes,
do not retry; inspect LinkedIn manually and use the controlled resolution
workflow.
