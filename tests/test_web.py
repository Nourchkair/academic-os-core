from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from academia_os import cli, web
from academia_os.config import save_config
from academia_os.web import (
    COMMAND_TIMEOUT_SECONDS,
    MAX_BODY_BYTES,
    MAX_UPLOAD_BYTES,
    CommandResult,
    DashboardServer,
    validate_loopback_host,
)
from tests.test_agent_neutral_core import minimal_config


@contextmanager
def running_server(
    tmp_path: Path,
    *,
    runner: Any | None = None,
    dist_dir: Path | None = None,
) -> Iterator[DashboardServer]:
    server = DashboardServer(port=0, dist_dir=dist_dir or (tmp_path / "dist"), runner=runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def request(
    server: DashboardServer,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(server.host, server.port, timeout=2)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, payload


def request_without_content_length(
    server: DashboardServer,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(server.host, server.port, timeout=2)
    connection.putrequest(method, path)
    for key, value in (headers or {}).items():
        connection.putheader(key, value)
    connection.endheaders()
    response = connection.getresponse()
    payload = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, payload


def command_body(command: str, args: list[str] | None = None) -> bytes:
    return json.dumps({"command": command, "args": args or []}).encode("utf-8")


def test_health_endpoint_returns_structured_local_service_status(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        status, headers, payload = request(server, "GET", "/api/v1/health")

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    value = json.loads(payload)
    assert value["status"] == "ok"
    assert value["service"] == "academia-dashboard"
    assert "access-control-allow-origin" not in headers


def test_cors_allows_only_the_local_frontend_origins(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        allowed_status, allowed_headers, _ = request(
            server,
            "GET",
            "/api/v1/health",
            headers={"Origin": "http://localhost:4173"},
        )
        alternate_status, alternate_headers, _ = request(
            server,
            "GET",
            "/api/v1/health",
            headers={"Origin": "http://127.0.0.1:4173"},
        )
        rejected_status, rejected_headers, rejected_payload = request(
            server,
            "GET",
            "/api/v1/health",
            headers={"Origin": "http://localhost:3000"},
        )

    assert allowed_status == 200
    assert allowed_headers["access-control-allow-origin"] == "http://localhost:4173"
    assert alternate_status == 200
    assert alternate_headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert rejected_status == 403
    assert "access-control-allow-origin" not in rejected_headers
    assert json.loads(rejected_payload)["type"] == "OriginNotAllowed"


def test_cors_allows_dynamic_same_origin_requests_and_errors(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")

    with running_server(tmp_path, dist_dir=dist, runner=lambda _command, _args: CommandResult(0, "{}", "")) as server:
        origins = (f"http://127.0.0.1:{server.port}", f"http://localhost:{server.port}")
        for origin in origins:
            health = request(server, "GET", "/api/v1/health", headers={"Origin": origin})
            static = request(server, "GET", "/", headers={"Origin": origin})
            missing = request(server, "GET", "/missing.js", headers={"Origin": origin})
            malformed = request(
                server,
                "POST",
                "/api/v1/command",
                body=b"not-json",
                headers={"Content-Type": "application/json", "Origin": origin},
            )
            preflight = request(
                server,
                "OPTIONS",
                "/api/v1/command",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )

            for response in (health, static, missing, malformed, preflight):
                assert response[1]["access-control-allow-origin"] == origin
                assert response[1]["vary"] == "Origin"
            assert health[0] == 200
            assert static[0] == 200
            assert missing[0] == 404
            assert malformed[0] == 400
            assert preflight[0] == 204

        other_port = request(
            server,
            "GET",
            "/api/v1/health",
            headers={"Origin": f"http://localhost:{server.port + 1}"},
        )
        other_host = request(
            server,
            "GET",
            "/api/v1/health",
            headers={"Origin": f"http://127.0.0.2:{server.port}"},
        )

    for response in (other_port, other_host):
        assert response[0] == 403
        assert "access-control-allow-origin" not in response[1]
        assert json.loads(response[2])["type"] == "OriginNotAllowed"


def test_unknown_and_dashboard_commands_are_rejected_before_runner(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(0, "{}", "")

    with running_server(tmp_path, runner=runner) as server:
        unknown = request(
            server,
            "POST",
            "/api/v1/command",
            body=command_body("not-a-command"),
            headers={"Content-Type": "application/json"},
        )
        dashboard = request(
            server,
            "POST",
            "/api/v1/command",
            body=command_body("dashboard"),
            headers={"Content-Type": "application/json"},
        )
        profile = request(
            server,
            "POST",
            "/api/v1/command",
            body=command_body("status", ["--profile", "secret-profile.json"]),
            headers={"Content-Type": "application/json"},
        )
        json_flag = request(
            server,
            "POST",
            "/api/v1/command",
            body=command_body("status", ["--json"]),
            headers={"Content-Type": "application/json"},
        )

    for status, _headers, payload in (unknown, dashboard, profile, json_flag):
        assert status == 400
        assert json.loads(payload)["type"] in {"CommandNotAllowed", "ArgumentNotAllowed"}
    assert calls == []


def test_malformed_and_oversized_json_return_structured_errors(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        malformed = request(
            server,
            "POST",
            "/api/v1/command",
            body=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        oversized = request(
            server,
            "POST",
            "/api/v1/command",
            body=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )

    assert malformed[0] == 400
    assert json.loads(malformed[2])["type"] == "MalformedJSON"
    assert oversized[0] == 413
    assert json.loads(oversized[2])["type"] == "RequestTooLarge"


def test_command_runner_receives_safe_args_and_cli_json_errors_are_preserved(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(2, json.dumps({"error": "profile is invalid", "type": "ValueError"}), "ignored stderr")

    with running_server(tmp_path, runner=runner) as server:
        status, _headers, payload = request(
            server,
            "POST",
            "/api/v1/command",
            body=command_body("status", ["--timezone", "UTC"]),
            headers={"Content-Type": "application/json"},
        )

    assert status == 422
    assert json.loads(payload) == {"error": "profile is invalid", "type": "ValueError"}
    assert calls == [("status", ["--timezone", "UTC", "--json"])]


def test_browser_upload_streams_to_import_runner_and_cleans_temporary_source(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []
    observed: dict[str, Any] = {}
    destination = tmp_path / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        observed["source_exists_during_runner"] = Path(args[0]).is_file()
        observed["bytes"] = Path(args[0]).read_bytes()
        return CommandResult(0, json.dumps({"source_type": "browser_upload", "destination": str(destination)}), "")

    query = urllib.parse.urlencode({"filename": "week-4.pdf", "destination": str(destination), "uncertain": "1"})
    with running_server(tmp_path, runner=runner) as server:
        status, _headers, payload = request(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            body=b"small browser bytes",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert status == 200
    assert json.loads(payload)["source_type"] == "browser_upload"
    assert observed == {"source_exists_during_runner": True, "bytes": b"small browser bytes"}
    assert len(calls) == 1
    command, args = calls[0]
    assert command == "import"
    assert args[1:] == [
        "--destination",
        str(destination),
        "--source-label",
        "browser-upload:week-4.pdf",
        "--uncertain",
        "--json",
    ]
    assert not Path(args[0]).exists()


@pytest.mark.parametrize("filename", ["../escape.pdf", "..\\escape.pdf", ".", "..", "bad\x00name.pdf", "x" * 256])
def test_browser_upload_rejects_invalid_filenames_before_runner(tmp_path: Path, filename: str) -> None:
    calls: list[tuple[str, list[str]]] = []
    destination = tmp_path / "Fall 2026" / "00_INBOX"

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(0, "{}", "")

    query = urllib.parse.urlencode({"filename": filename, "destination": str(destination)})
    with running_server(tmp_path, runner=runner) as server:
        status, _headers, payload = request(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            body=b"not imported",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert status == 400
    assert json.loads(payload)["type"] == "InvalidFilename"
    assert calls == []


def test_browser_upload_requires_content_length_and_has_a_separate_size_limit(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(0, "{}", "")

    query = urllib.parse.urlencode({"filename": "small.txt", "destination": str(tmp_path / "Fall 2026" / "00_INBOX")})
    with running_server(tmp_path, runner=runner) as server:
        missing = request_without_content_length(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            headers={"Content-Type": "application/octet-stream"},
        )
        oversized = request(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            body=b"one byte",
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(MAX_UPLOAD_BYTES + 1)},
        )

    assert missing[0] == 400
    assert json.loads(missing[2])["type"] == "MissingContentLength"
    assert oversized[0] == 413
    assert json.loads(oversized[2])["type"] == "UploadTooLarge"
    assert MAX_UPLOAD_BYTES > MAX_BODY_BYTES
    assert calls == []


def test_browser_upload_rejects_wrong_media_type_without_runner(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(0, "{}", "")

    query = urllib.parse.urlencode({"filename": "notes.txt", "destination": str(tmp_path / "Fall 2026" / "00_INBOX")})
    with running_server(tmp_path, runner=runner) as server:
        status, _headers, payload = request(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            body=b"not imported",
            headers={"Content-Type": "text/plain"},
        )

    assert status == 415
    assert json.loads(payload)["type"] == "UnsupportedMediaType"
    assert calls == []


def test_browser_upload_uses_the_same_origin_rejection_and_is_not_a_get_endpoint(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def runner(command: str, args: list[str]) -> CommandResult:
        calls.append((command, args))
        return CommandResult(0, "{}", "")

    query = urllib.parse.urlencode({"filename": "notes.txt", "destination": str(tmp_path / "Fall 2026" / "00_INBOX")})
    with running_server(tmp_path, runner=runner) as server:
        rejected = request(
            server,
            "POST",
            f"/api/v1/upload?{query}",
            body=b"not imported",
            headers={"Content-Type": "application/octet-stream", "Origin": "http://localhost:3000"},
        )
        get_upload = request(server, "GET", f"/api/v1/upload?{query}")

    assert rejected[0] == 403
    assert json.loads(rejected[2])["type"] == "OriginNotAllowed"
    assert get_upload[0] == 404
    assert json.loads(get_upload[2])["type"] == "NotFound"
    assert calls == []



def test_static_files_have_spa_fallback_and_traversal_protection(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (dist / "asset.txt").write_text("safe asset", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("do not serve", encoding="utf-8")
    (dist / "outside-link.txt").symlink_to(outside)

    with running_server(tmp_path, dist_dir=dist) as server:
        asset = request(server, "GET", "/asset.txt")
        spa = request(server, "GET", "/courses/123")
        traversal = request(server, "GET", "/%2e%2e/outside.txt")
        symlink = request(server, "GET", "/outside-link.txt")

    assert asset[0] == 200
    assert asset[2] == b"safe asset"
    assert spa[0] == 200
    assert spa[2] == b"<html>dashboard</html>"
    assert traversal[0] in {403, 404}
    assert b"do not serve" not in traversal[2]
    assert symlink[0] in {403, 404}
    assert b"do not serve" not in symlink[2]


def test_missing_dist_returns_setup_html_instead_of_directory_listing(tmp_path: Path) -> None:
    with running_server(tmp_path, dist_dir=tmp_path / "missing-dist") as server:
        status, headers, payload = request(server, "GET", "/")

    assert status == 503
    assert headers["content-type"].startswith("text/html")
    assert b"npm run build" in payload
    assert b"Directory listing" not in payload


def test_symlinked_dist_returns_setup_response_without_reading_target(tmp_path: Path) -> None:
    target = tmp_path / "target-dist"
    target.mkdir()
    (target / "index.html").write_text("target must not be served", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.symlink_to(target, target_is_directory=True)

    with running_server(tmp_path, dist_dir=dist) as server:
        status, _headers, payload = request(server, "GET", "/")

    assert status == 503
    assert b"target must not be served" not in payload
    assert b"npm run build" in payload


def test_dashboard_host_validation_accepts_loopback_and_rejects_remote_hosts() -> None:
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("localhost") == "localhost"
    assert validate_loopback_host("::1") == "::1"
    for host in ("0.0.0.0", "192.168.1.10", "example.com"):
        with pytest.raises(ValueError, match="loopback"):
            validate_loopback_host(host)


def test_dashboard_parser_and_launcher_forward_loopback_options(monkeypatch: pytest.MonkeyPatch) -> None:
    args = cli.build_parser().parse_args(["dashboard", "--host", "127.0.0.1", "--port", "8876", "--open"])
    assert args.command == "dashboard"
    assert args.host == "127.0.0.1"
    assert args.port == 8876
    assert args.open is True

    calls: list[dict[str, Any]] = []

    def fake_serve_dashboard(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(cli, "serve_dashboard", fake_serve_dashboard)
    assert cli.main(["dashboard", "--host", "localhost", "--port", "8877"]) == 0
    assert calls == [{"host": "localhost", "port": 8877, "open_browser": True, "profile": None}]


def test_bare_academia_command_opens_the_dashboard(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "serve_dashboard", lambda **kwargs: calls.append(kwargs))

    assert cli.main([]) == 0

    assert calls == [{"host": "127.0.0.1", "port": 8765, "open_browser": True, "profile": None}]


def test_dashboard_can_run_without_opening_a_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "serve_dashboard", lambda **kwargs: calls.append(kwargs))

    assert cli.main(["dashboard", "--no-open"]) == 0

    assert calls == [{"host": "127.0.0.1", "port": 8765, "open_browser": False, "profile": None}]


def test_dashboard_parser_rejects_non_loopback_at_launch(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "serve_dashboard", lambda **_kwargs: pytest.fail("launcher should not run"))
    assert cli.main(["dashboard", "--host", "0.0.0.0"]) == 2
    assert "loopback" in capsys.readouterr().err


def test_default_command_timeout_is_suitable_for_local_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    def fake_run(_argv: list[str], **kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(web.subprocess, "run", fake_run)
    result = web.run_cli_command("migration", ["status"])

    assert result.returncode == 0
    assert COMMAND_TIMEOUT_SECONDS >= 120
    assert observed["timeout"] == COMMAND_TIMEOUT_SECONDS
    assert observed["shell"] is False


def test_serve_dashboard_prints_bound_url_before_opening_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, Any]] = []

    class FakeServer:
        url = "http://127.0.0.1:45678/"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            events.append(("bind", self.url))

        def serve_forever(self) -> None:
            events.append(("serve", None))
            raise KeyboardInterrupt

        def server_close(self) -> None:
            events.append(("close", None))

    def fake_print(*args: Any, **kwargs: Any) -> None:
        events.append(("print", (args, kwargs)))

    monkeypatch.setattr(web, "DashboardServer", FakeServer)
    monkeypatch.setattr(web.webbrowser, "open", lambda url: events.append(("open", url)))
    monkeypatch.setattr("builtins.print", fake_print)

    result = web.serve_dashboard(port=0, open_browser=True)

    assert isinstance(result, FakeServer)
    assert [event[0] for event in events] == ["bind", "print", "open", "serve", "close"]
    assert events[1][1] == (("Academia dashboard listening at http://127.0.0.1:45678/",), {"flush": True})


def test_file_preview_endpoint_reads_active_library_file_and_rejects_outside_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    monkeypatch.setenv("ACADEMIC_OS_CONFIG", str(profile))
    root = Path(config["academic"]["root_directory"])
    source = root / "Fall 2026" / "HIS 101 - History" / "00_INBOX" / "week-4.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Week 4\n\nRead locally.", encoding="utf-8")
    old_source = root / "Spring 2025" / "HIS 101 - History" / "05_REFERENCE" / "old-reading.md"
    old_source.parent.mkdir(parents=True)
    old_source.write_text("# Older reading", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    server = DashboardServer(port=0, dist_dir=dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        encoded = urllib.parse.quote(str(source), safe="")
        status, headers, payload = request(server, "GET", f"/api/v1/file-preview?path={encoded}")
        raw_status, raw_headers, raw_payload = request(server, "GET", f"/api/v1/file?path={encoded}")
        old_encoded = urllib.parse.quote(str(old_source), safe="")
        old_status, _old_headers, old_payload = request(server, "GET", f"/api/v1/file-preview?path={old_encoded}&semester={urllib.parse.quote('Spring 2025')}")
        outside_path = tmp_path / "private.md"
        outside_path.write_text("do not serve", encoding="utf-8")
        outside = urllib.parse.quote(str(outside_path), safe="")
        outside_status, _outside_headers, _outside_payload = request(server, "GET", f"/api/v1/file-preview?path={outside}")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(payload)["content"] == "# Week 4\n\nRead locally."
    assert raw_status == 200
    assert raw_headers["content-type"].startswith("text/markdown")
    assert raw_payload == source.read_bytes()
    assert old_status == 200
    assert json.loads(old_payload)["content"] == "# Older reading"
    assert outside_status == 403
