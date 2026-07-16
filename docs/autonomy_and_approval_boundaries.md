# Autonomy and Approval Boundaries

Phase 8D permits preparation of a content package from an already stored, source-traced opportunity. Preparation is not publication. “Approve for later posting” is only an internal SQLite status and has no LinkedIn external action.

No Phase 8D path fetches LinkedIn, scrapes LinkedIn, invokes the publishing wrapper, schedules a post, or posts automatically. Human approval remains required for every future external action.

Phase 8G does not relax this rule. An approved package is eligible only to
create a frozen preview. A LinkedIn write additionally requires an unexpired,
current request ID and explicit `/confirm_publish <request_id>`. Freeform text,
briefings, schedulers, models, prospect workflows, outreach workflows, calendar
workflows, OAuth callbacks, and malformed/replayed Telegram callbacks cannot
publish. Disabled and mock modes make no LinkedIn network request.
