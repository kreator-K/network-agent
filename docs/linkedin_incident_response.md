# LinkedIn Publishing Incident Response

1. Set `LINKEDIN_REAL_PUBLISH_ENABLED=false` in `.env.local` and restart the
   bot. Do not edit the template file as an operational control.
2. Run `/linkedin_publish_diagnostics`, `/publish_history`, and
   `/publish_request <request_id>`.
3. For any uncertain result, inspect the member's LinkedIn activity manually.
   Do not retry or prepare another request for the same package version.
4. Record the decision with
   `/resolve_publish_uncertain <request_id> posted|not_posted`. This command
   never contacts LinkedIn.
5. Back up SQLite before manual database investigation. Never copy
   `.env.local`, credential keys, or temporary upload URLs into an incident
   artifact.
6. Reauthorize through `/linkedin_reauthorize` if credentials are expired,
   revoked, undecryptable, or missing `w_member_social`.

Logs and reports may contain request/package IDs, fingerprints, stages,
durations, and safe status codes. They must not contain tokens, OAuth codes,
raw state, authorization headers, full upload URLs, or client secrets.
