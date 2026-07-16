# LinkedIn SQLite Backup and Restore

Use the SQLite online backup API in `db.backup`; do not copy a live database
file with a plain filesystem copy.

```python
from db.backup import backup_database, restore_database

backup_database("network_agent.db", "/secure/offline/network_agent.backup.db")
restore_database("/secure/offline/network_agent.backup.db", "restored.db")
```

Operational procedure:

1. Disable real publishing and restart.
2. Create and verify the backup on access-controlled storage.
3. Restore to a separate path and point `DATABASE_PATH` to it only after
   validation.
4. Start the application. Startup reconciliation marks interrupted writes
   uncertain and never resumes them.
5. Run `/system_check` and `/linkedin_publish_diagnostics`.

Encrypted credential rows remain encrypted and require the same external
encryption key. The key and `.env.local` are not database backup artifacts.
