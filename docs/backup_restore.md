# Backup and Restore Procedure

The supported helpers are `db.backup.backup_database` and
`db.backup.restore_database`. They use SQLite's online backup API and never
copy `.env.local`, credentials, tokens, or secrets.

```python
from db.backup import backup_database, restore_database

backup_database("network_agent.db", "backups/network-agent-YYYYMMDD-HHMMSS.db")
restore_database("backups/network-agent-YYYYMMDD-HHMMSS.db", "restore-test.db")
```

Always restore to a temporary path first, initialize the schema, run
`/system_check`, and inspect the release check output. Interrupted publishing
operations become uncertain after startup reconciliation; no external write is
resumed automatically. Replacing the active database is an explicit operator
action outside the release script.
