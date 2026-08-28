# Network Growth Agent Web

Next.js 16.3.3 App Router frontend for Vercel. The current foundation contains
the responsive application shell, dashboard, Signals, Opportunities, and
Content Studio routes, plus a server-only backend client.

Set `NETWORK_API_BASE_URL`, `WEB_API_TOKEN`, `WEB_SESSION_SECRET`, and
`WEB_OWNER_PASSWORD_HASH` only in the Vercel server environment. The API token
and session values must never use a `NEXT_PUBLIC_` variable or an
unauthenticated proxy route. Generate the password value with
`npm run hash-password -- '<strong password>'`.

Run `npm install`, `npm run typecheck`, and `npm run build` before deployment.
The signed owner cookie is HTTP-only, secure in production, strict same-site,
and expires after eight hours. Interactive mutations remain deferred until
dedicated action contracts and CSRF defenses are implemented.
