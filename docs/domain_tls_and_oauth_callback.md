# Domain, TLS, and OAuth Callback

Production uses one stable HTTPS domain, managed certificate renewal, HTTP to
HTTPS redirection, and a reverse proxy that forwards only the callback and
health paths to the local callback adapter. The exact LinkedIn Developer
Portal redirect URI is:

`https://<stable-domain>/v1/callback`

Replace `<stable-domain>` with the operator-owned domain in both `.env.local`
and the LinkedIn portal. Temporary ngrok and Postman callback URLs are not
production instructions. The callback adapter does not expose debug pages or
stack traces.
