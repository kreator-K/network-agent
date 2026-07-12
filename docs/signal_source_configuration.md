# Signal Source Configuration

## Finding A Feed

Use a public RSS or Atom feed URL provided by the publisher. Do not add LinkedIn URLs, arbitrary article pages, internal hosts, or feeds containing credentials.

## Workflow

```text
/add_signal_source Example | https://example.org/feed.xml
/approve_signal_source 3
/enable_signal_source 3
/scan_signal_source 3
```

Use `/disable_signal_source 3` to stop manual scans without deleting history. `/reject_signal_source 3` rejects and disables a pending source.

## Security Restrictions

HTTPS is required by default. The application blocks LinkedIn, localhost, private and reserved IP ranges, metadata hosts, embedded credentials, unsafe redirect targets, oversized responses, and unsupported content types.

## Retention

SQLite stores source attribution, feed metadata, short feed-item fields, normalized content, and hashes. It does not fetch arbitrary article pages or retain full feed bodies. Source seed configuration is empty by default; source records are managed in SQLite through approved workflows.
