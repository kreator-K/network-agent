"""Run the small HTTPS-adapter callback handler behind a configured proxy.

The application deliberately does not terminate TLS itself. Deploy this
process behind an HTTPS reverse proxy whose exact public callback URI matches
LINKEDIN_REDIRECT_URI.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestrator import NetworkOrchestrator
from config.settings import settings
from db.database import initialize_database


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        configured_path = urlparse(settings.linkedin_redirect_uri).path
        if self.path.split("?", 1)[0] != configured_path:
            self.send_error(404)
            return
        params = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items() if values}
        try:
            result = NetworkOrchestrator().complete_linkedin_authorization(params, database=settings.database_path)
            body = str(result["browser_html"]).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            reference = ""
            marker = "LI-OAUTH-"
            text = str(exc)
            if marker in text:
                reference = text[text.index(marker):].split(":", 1)[0]
            suffix = f"<p>Reference: {reference}</p>" if reference else ""
            body = ("<!doctype html><html><body><p>LinkedIn authorization could not be completed.</p>" + suffix + "<p>Return to Telegram and run /linkedin_connect again.</p></body></html>").encode("utf-8")
            self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    initialize_database(settings.database_path)
    HTTPServer(("127.0.0.1", 8080), CallbackHandler).serve_forever()
