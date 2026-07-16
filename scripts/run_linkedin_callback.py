"""Run the small HTTPS-adapter callback handler behind a configured proxy.

The application deliberately does not terminate TLS itself. Deploy this
process behind an HTTPS reverse proxy whose exact public callback URI matches
LINKEDIN_REDIRECT_URI.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestrator import NetworkOrchestrator
from config.settings import settings
from db.database import connect, initialize_database


logger = logging.getLogger(__name__)


def health_payload() -> dict[str, object]:
    return {"status": "ok", "service": "linkedin-callback"}


def readiness_payload() -> tuple[int, dict[str, object]]:
    try:
        with connect(settings.database_path) as connection:
            row = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='linkedin_oauth_states'").fetchone()
            if row is None:
                raise RuntimeError("database migrations are not current")
        return 200, {"status": "ready", "database": "reachable", "configuration": "loaded"}
    except Exception as exc:
        logger.warning("Callback readiness failed: error_type=%s", type(exc).__name__)
        return 503, {"status": "not_ready", "reason": "local_dependency_unavailable"}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json_response(200, health_payload())
            return
        if path == "/readyz":
            status, payload = readiness_payload()
            self._json_response(status, payload)
            return
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    """Run the callback adapter and close its listening socket on Ctrl+C."""
    initialize_database(settings.database_path)
    server = HTTPServer((settings.callback_host, settings.callback_port), CallbackHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("LinkedIn callback shutdown requested.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
