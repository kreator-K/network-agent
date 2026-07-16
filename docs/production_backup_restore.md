# Production Backup and Restore

Run `python scripts/backup_database.py --output <timestamped-path>` as the
dedicated service account. Verify with
`python scripts/verify_backup.py --backup <path>`. Keep backups in a restricted
directory with a configurable retention policy and never copy `.env.local`.

Restore only to a temporary directory during routine verification. A live
restore requires operator confirmation, a stopped writable process, an
integrity check, and explicit review that uncertain LinkedIn operations will
not resume automatically.
