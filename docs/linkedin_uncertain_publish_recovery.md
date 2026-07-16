# LinkedIn Uncertain Publish Recovery

Timeouts, connection resets, rate limits, server errors, malformed success
responses, and interrupted in-progress writes are uncertain. The request blocks
replay and automatic retry. Inspect the authenticated LinkedIn account manually,
then use `/resolve_publish_uncertain <request_id> posted|not_posted`. Resolution
records operator knowledge; it does not make another provider write.
