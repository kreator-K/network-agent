# Network Growth Agent Web

Next.js 16.3.3 App Router frontend for Vercel. The current foundation contains
the responsive application shell, dashboard, Signals, Opportunities, and
Content Studio routes, plus a server-only backend client.

Set `NETWORK_API_BASE_URL` and `WEB_API_TOKEN` only in the Vercel server
environment. The token must never use a `NEXT_PUBLIC_` variable or an
unauthenticated proxy route.

Run `npm install`, `npm run typecheck`, and `npm run build` before deployment.
Interactive mutations remain deferred until browser session and CSRF protection
are implemented.
