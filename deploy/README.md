# Web deployment target

The former Phase 10 systemd target is retired. The Next.js UI deploys on Vercel.
The Python 3.11 API remains a separate service because Vercel's current Python
runtime does not support 3.11. The legacy Telegram adapter is not active.

Keep `.env.local` outside the Git release artifact and review
`docs/vercel_deployment.md` before exposing a web route. The old unit files are
historical migration references and must not be enabled.

```bash
python scripts/pre_deploy.py
curl -fsS https://<python-api>/healthz
```

Do not expose the future API without authentication, stable HTTPS, and a
reviewed persistence strategy. Do not run more than one writable backend
process against the same SQLite database.
