# Deployment Rollback

The operational sequence is precheck -> backup -> stop -> deploy -> migrate
-> start -> readiness -> smoke test. On failure, stop the failed release and
preserve safe logs. Reinstall the previous application release and rerun
readiness. Restore SQLite only if the migration changed data and the rollback
plan explicitly requires it. Never replay external writes during rollback.
