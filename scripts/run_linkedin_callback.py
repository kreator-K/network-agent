"""Run the small HTTPS-adapter callback handler behind a configured proxy.

The application deliberately does not terminate TLS itself. Deploy this
process behind an HTTPS reverse proxy whose exact public callback URI matches
LINKEDIN_REDIRECT_URI.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from agents.orchestrator import NetworkOrchestrator
from config.settings import settings


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/oauth/linkedin/callback":
            self.send_error(404)
            return
        params = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items() if values}
        try:
            result = NetworkOrchestrator().complete_linkedin_authorization(params, database=settings.database_path)
            body = str(result["browser_html"]).encode("utf-8")
            self.send_response(200)
        except Exception:
            body = b"<!doctype html><html><body><p>LinkedIn authorization failed or expired. Nothing was published.</p></body></html>"
            self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8080), CallbackHandler).serve_forever()
