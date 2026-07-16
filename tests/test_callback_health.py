"""Read-only callback health endpoint tests."""

from scripts import run_linkedin_callback


def test_health_payload_contains_no_runtime_values() -> None:
    payload = run_linkedin_callback.health_payload()
    assert payload == {"status": "ok", "service": "linkedin-callback"}


def test_readiness_reports_database_failure_without_details(monkeypatch) -> None:
    def fail(_path):
        raise RuntimeError("private database detail")

    monkeypatch.setattr(run_linkedin_callback, "connect", fail)
    status, payload = run_linkedin_callback.readiness_payload()
    assert status == 503
    assert payload == {"status": "not_ready", "reason": "local_dependency_unavailable"}
    assert "private" not in repr(payload)


def test_main_closes_server_cleanly_on_keyboard_interrupt(monkeypatch) -> None:
    class Server:
        closed = False

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    server = Server()
    monkeypatch.setattr(run_linkedin_callback, "initialize_database", lambda _path: None)
    monkeypatch.setattr(run_linkedin_callback, "HTTPServer", lambda *_args: server)
    assert run_linkedin_callback.main() == 0
    assert server.closed is True
