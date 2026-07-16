# LinkedIn Real Publish Runbook

Keep publishing disabled during development. For a live test, select one
already-approved package, enable both real controls, restart the bot, inspect
`/linkedin_publish_status`, run `/prepare_publish <post_id>`, review the complete
frozen preview, and explicitly run `/confirm_publish <request_id>`. Verify the
result manually on LinkedIn, then disable the kill switch and restart the bot.

Never begin with a rich-media package. Never reuse or retry an uncertain request.
