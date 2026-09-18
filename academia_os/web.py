from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import SEMESTER_PATTERN, load_config
from .file_preview import FilePreviewError, TEXT_EXTENSIONS, preview_file, resolve_library_file
from .workspace import build_workspace_snapshot

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_FILENAME_BYTES = 255
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ARGUMENTS = 32
MAX_ARGUMENT_LENGTH = 1024
COMMAND_TIMEOUT_SECONDS = 120.0


def default_profile_path() -> Path:
    """Return the same profile path used by the public CLI by default."""

    return Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser().resolve()

# Keep this in sync with the already-approved local Tauri command surface.  The
# browser transport is intentionally narrower than a general CLI shell: the
# command name is selected from this fixed set and arguments are passed without
# shell interpretation.
SAFE_COMMANDS = frozenset(
    {
        "status",
        "courses",
        "course",
        "today",
        "tasks",
        "review",
        "activity",
        "workspace",
        "semester",
        "inbox",
        "import",
        "domain",
        "library",
        "file-preview",
        "extract",
        "migration",
        "settings",
        "capabilities",
        "watch",
        "verify",
        "verify-source",
        "agents",
        "agent",
        "artifact",
    }
)
ALLOWED_ORIGINS = frozenset({"http://localhost:4173", "http://127.0.0.1:4173"})


def _allowed_origins(host: str, port: int) -> frozenset[str]:
    """Return the fixed Vite origins plus this server's loopback origin(s)."""

    if host.casefold() == "localhost" or host == "127.0.0.1":
        hosts = ("localhost", "127.0.0.1")
    else:
        hosts = (host,)
    loopback_origins = {
        f"http://{f'[{origin_host}]' if ':' in origin_host else origin_host}:{port}"
        for origin_host in hosts
    }
    return frozenset(ALLOWED_ORIGINS | loopback_origins)

_SETUP_HTML = """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Academia OS dashboard setup</title></head>
  <body>
    <h1>Academia OS dashboard is not built yet</h1>
    <p>Build the browser frontend first:</p>
    <pre>cd frontend
npm install
npm run build</pre>
    <p>Then run <code>academia dashboard</code> again.</p>
  </body>
</html>
"""


class DashboardRequestError(Exception):
    """An expected, structured HTTP/API validation failure."""

    def __init__(self, status: int, error_type: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.message = message


class CommandTimeoutError(Exception):
    """The delegated CLI command exceeded the dashboard timeout."""


@dataclass(frozen=True)
class CommandResult:
    """The small result contract accepted from an injected CLI runner."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[str, list[str]], CommandResult]


def validate_loopback_host(host: str) -> str:
    """Return *host* if it is an explicitly loopback-only bind address."""

    if not isinstance(host, str) or not host:
        raise ValueError("dashboard host must be a loopback address")
    if host.casefold() == "localhost":
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("dashboard host must be a loopback address") from exc
    if not address.is_loopback:
        raise ValueError("dashboard host must be a loopback address")
    return host


def run_cli_command(
    command: str,
    args: Sequence[str],
    *,
    profile: Path | None = None,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run an approved CLI command without invoking a shell."""

    argv = [sys.executable, "-m", "academia_os"]
    if profile is not None:
        argv.extend(("--profile", str(profile)))
    argv.extend((command, *args))
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(f"academia command timed out after {timeout:g} seconds") from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _coerce_command_result(result: Any) -> CommandResult:
    if isinstance(result, CommandResult):
        return result
    if isinstance(result, subprocess.CompletedProcess):
        return CommandResult(int(result.returncode), str(result.stdout or ""), str(result.stderr or ""))
    if isinstance(result, tuple) and len(result) == 3:
        return CommandResult(int(result[0]), str(result[1] or ""), str(result[2] or ""))
    raise TypeError("dashboard runner must return CommandResult or CompletedProcess")


class _DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _DashboardHTTPServerV6(_DashboardHTTPServer):
    address_family = socket.AF_INET6


class DashboardServer:
    """A localhost-only HTTP server for the browser dashboard."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        profile: Path | None = None,
        dist_dir: Path | None = None,
        runner: Callable[[str, list[str]], Any] | None = None,
        command_timeout: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self.host = validate_loopback_host(host)
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("dashboard port must be between 0 and 65535")
        if command_timeout <= 0:
            raise ValueError("dashboard command timeout must be positive")
        # Direct routes such as file preview need the concrete profile path,
        # while CLI-backed routes already resolve this default internally.
        # Normalize it here so both transports read the same workspace.
        self.profile = (profile or default_profile_path()).expanduser().resolve()
        self.dist_dir = (dist_dir or Path(__file__).resolve().parents[1] / "frontend" / "dist").expanduser()
        self.command_timeout = command_timeout
        self.runner = runner or self._default_runner
        server_class = _DashboardHTTPServerV6 if ":" in self.host else _DashboardHTTPServer
        self._httpd = server_class((self.host, port), _DashboardRequestHandler)
        self.allowed_origins = _allowed_origins(self.host, self.port)
        self._httpd.dashboard = self  # type: ignore[attr-defined]

    @property
    def server_address(self) -> tuple[str, int]:
        address = self._httpd.server_address
        return str(address[0]), int(address[1])

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/"

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")

    def _default_runner(self, command: str, args: list[str]) -> CommandResult:
        return run_cli_command(command, args, profile=self.profile, timeout=self.command_timeout)

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        self._httpd.shutdown()

    def server_close(self) -> None:
        self._httpd.server_close()

    close = server_close


def serve_dashboard(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    profile: Path | None = None,
    dist_dir: Path | None = None,
    runner: Callable[[str, list[str]], Any] | None = None,
    command_timeout: float = COMMAND_TIMEOUT_SECONDS,
    open_browser: bool = False,
) -> DashboardServer:
    """Bind and serve the dashboard, stopping cleanly on Ctrl-C."""

    server = DashboardServer(
        host,
        port,
        profile=profile,
        dist_dir=dist_dir,
        runner=runner,
        command_timeout=command_timeout,
    )
    try:
        # DashboardServer binds synchronously in its constructor, so the URL is
        # ready before opening a browser and before entering serve_forever().
        print(f"Academia dashboard listening at {server.url}", flush=True)
        if open_browser:
            webbrowser.open(server.url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server


class _DashboardRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "AcademiaDashboard"
    sys_version = ""

    @property
    def dashboard(self) -> DashboardServer:
        return self.server.dashboard  # type: ignore[attr-defined]

    @property
    def request_path(self) -> str:
        return urllib.parse.urlsplit(self.path).path

    def log_message(self, format: str, *args: object) -> None:
        # Do not write request paths, query strings, or local data to stdout.
        del format, args
        return

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        cors_origin: str | None = None,
        extra_headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type.startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
        self.close_connection = True

    def _send_json(self, status: int, value: Any, *, cors_origin: str | None = None) -> None:
        body = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", cors_origin=cors_origin)

    def _send_api_error(self, error: DashboardRequestError, *, cors_origin: str | None = None) -> None:
        self._send_json(
            error.status,
            {"error": error.message, "type": error.error_type},
            cors_origin=cors_origin,
        )

    def _request_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin and origin not in self.dashboard.allowed_origins:
            self._send_api_error(DashboardRequestError(403, "OriginNotAllowed", "request Origin is not allowed"))
            return None
        return origin

    def _is_api_request(self) -> bool:
        return self.request_path.startswith("/api/")

    def do_OPTIONS(self) -> None:
        origin = self._request_origin()
        if self.headers.get("Origin") and origin is None:
            return
        if not self._is_api_request():
            self._send_bytes(405, b"Method Not Allowed\n", "text/plain; charset=utf-8", cors_origin=origin)
            return
        if self.request_path == "/api/v1/upload":
            allow_methods = "POST, OPTIONS"
        else:
            allow_methods = "GET, POST, OPTIONS"
        self._send_bytes(
            204,
            b"",
            "text/plain; charset=utf-8",
            cors_origin=origin,
            extra_headers={
                "Allow": allow_methods,
                "Access-Control-Allow-Methods": allow_methods,
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
            },
        )

    def do_GET(self) -> None:
        origin = self._request_origin()
        if self.headers.get("Origin") and origin is None:
            return
        if self._is_api_request():
            if self.request_path == "/api/v1/health":
                self._send_json(
                    200,
                    {"status": "ok", "service": "academia-dashboard", "commands": sorted(SAFE_COMMANDS)},
                    cors_origin=origin,
                )
            elif self.request_path == "/api/v1/file-preview":
                self._handle_file_preview(origin)
            elif self.request_path == "/api/v1/file":
                self._handle_file(origin, head_only=False)
            else:
                self._send_api_error(
                    DashboardRequestError(404, "NotFound", "API endpoint not found"),
                    cors_origin=origin,
                )
            return
        self._serve_static(head_only=False, cors_origin=origin)

    def do_HEAD(self) -> None:
        origin = self._request_origin()
        if self.headers.get("Origin") and origin is None:
            return
        if self._is_api_request():
            if self.request_path == "/api/v1/health":
                body = (json.dumps({"status": "ok", "service": "academia-dashboard", "commands": sorted(SAFE_COMMANDS)}, separators=(",", ":")) + "\n").encode("utf-8")
                self._send_bytes(200, body, "application/json; charset=utf-8", cors_origin=origin, head_only=True)
            elif self.request_path == "/api/v1/file":
                self._handle_file(origin, head_only=True)
            elif self.request_path == "/api/v1/file-preview":
                self._handle_file_preview(origin, head_only=True)
            else:
                self._send_api_error(DashboardRequestError(404, "NotFound", "API endpoint not found"), cors_origin=origin)
            return
        self._serve_static(head_only=True, cors_origin=origin)

    def do_POST(self) -> None:
        origin = self._request_origin()
        if self.headers.get("Origin") and origin is None:
            return
        if self.request_path == "/api/v1/upload":
            self._handle_upload(origin)
            return
        if self.request_path != "/api/v1/command":
            if self._is_api_request():
                self._send_api_error(DashboardRequestError(404, "NotFound", "API endpoint not found"), cors_origin=origin)
            else:
                self._send_bytes(405, b"Method Not Allowed\n", "text/plain; charset=utf-8", cors_origin=origin)
            return
        try:
            command, args = self._parse_command_request()
            result = _coerce_command_result(self.dashboard.runner(command, [*args, "--json"]))
        except DashboardRequestError as exc:
            self._send_api_error(exc, cors_origin=origin)
            return
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            self._send_api_error(
                DashboardRequestError(504, "CommandTimeout", "academia command timed out"),
                cors_origin=origin,
            )
            return
        except (OSError, TypeError, ValueError) as exc:
            self._send_api_error(
                DashboardRequestError(500, "RunnerError", f"could not run academia command: {exc}"),
                cors_origin=origin,
            )
            return

        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            if result.returncode == 0:
                self._send_api_error(
                    DashboardRequestError(502, "InvalidCLIResponse", "academia command did not return JSON"),
                    cors_origin=origin,
                )
            else:
                self._send_api_error(
                    DashboardRequestError(502, "CLIError", "academia command failed without a JSON error"),
                    cors_origin=origin,
                )
            return
        self._send_json(200 if result.returncode == 0 else 422, value, cors_origin=origin)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        origin = self._request_origin()
        if self.headers.get("Origin") and origin is None:
            return
        if self._is_api_request():
            self._send_api_error(DashboardRequestError(405, "MethodNotAllowed", "API method not allowed"), cors_origin=origin)
        else:
            self._send_bytes(405, b"Method Not Allowed\n", "text/plain; charset=utf-8", cors_origin=origin)

    def _file_query_path(self) -> Path:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
        values = query.get("path")
        if not values or len(values) != 1 or not values[0] or "\x00" in values[0]:
            raise DashboardRequestError(400, "InvalidFilePath", "a single Library file path is required")
        return Path(values[0]).expanduser()

    def _active_workspace_for_file(self) -> tuple[Path, str]:
        if self.dashboard.profile is None:
            raise DashboardRequestError(503, "WorkspaceUnavailable", "file previews require an active local workspace profile")
        try:
            config = load_config(self.dashboard.profile)
            snapshot = build_workspace_snapshot(config)
            return Path(snapshot["academic_root"]), str(snapshot["semester"])
        except (OSError, KeyError, ValueError) as exc:
            raise DashboardRequestError(503, "WorkspaceUnavailable", "the active local workspace could not be loaded") from exc

    def _file_query_semester(self, workspace_root: Path, default: str) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
        values = query.get("semester")
        if not values:
            return default
        if len(values) != 1 or not values[0] or not SEMESTER_PATTERN.fullmatch(values[0]):
            raise DashboardRequestError(400, "InvalidSemester", "a valid semester label is required")
        semester = values[0]
        if not (workspace_root / semester).is_dir():
            raise DashboardRequestError(404, "SemesterNotFound", "the requested semester is not present in the local workspace")
        return semester

    @staticmethod
    def _file_preview_error(exc: FilePreviewError) -> DashboardRequestError:
        message = str(exc)
        if "not part of the active semester" in message or "absolute local file path" in message or "regular file" in message:
            status, error_type = 403, "FileNotAllowed"
        elif "not available" in message:
            status, error_type = 415, "UnsupportedFileType"
        else:
            status, error_type = 422, "FilePreviewError"
        return DashboardRequestError(status, error_type, message)

    def _handle_file_preview(self, origin: str | None, *, head_only: bool = False) -> None:
        try:
            path = self._file_query_path()
            workspace_root, active_semester = self._active_workspace_for_file()
            semester = self._file_query_semester(workspace_root, active_semester)
            value = preview_file(path, workspace_root=workspace_root, semester=semester)
        except DashboardRequestError as exc:
            self._send_api_error(exc, cors_origin=origin)
            return
        except FilePreviewError as exc:
            self._send_api_error(self._file_preview_error(exc), cors_origin=origin)
            return
        body = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self._send_bytes(200, body, "application/json; charset=utf-8", cors_origin=origin, head_only=head_only)

    def _handle_file(self, origin: str | None, *, head_only: bool) -> None:
        try:
            path = self._file_query_path()
            workspace_root, active_semester = self._active_workspace_for_file()
            semester = self._file_query_semester(workspace_root, active_semester)
            resolved, item = resolve_library_file(path, workspace_root=workspace_root, semester=semester)
            extension = str(item.get("extension", "")).casefold()
            if extension != ".pdf" and extension not in TEXT_EXTENSIONS:
                raise DashboardRequestError(415, "UnsupportedFileType", "the raw file endpoint is limited to readable Library files")
            if resolved.stat().st_size > MAX_UPLOAD_BYTES:
                raise DashboardRequestError(413, "FileTooLarge", "the selected file is too large to preview")
            body = resolved.read_bytes()
        except DashboardRequestError as exc:
            self._send_api_error(exc, cors_origin=origin)
            return
        except FilePreviewError as exc:
            self._send_api_error(self._file_preview_error(exc), cors_origin=origin)
            return
        except OSError:
            self._send_api_error(DashboardRequestError(422, "FileReadError", "the selected file could not be read"), cors_origin=origin)
            return
        content_type = "application/pdf" if extension == ".pdf" else ("text/markdown; charset=utf-8" if extension in {".md", ".markdown"} else "text/plain; charset=utf-8")
        self._send_bytes(
            200,
            body,
            content_type,
            cors_origin=origin,
            extra_headers={"Content-Disposition": f'inline; filename="{resolved.name.replace(chr(34), "")}"'},
            head_only=head_only,
        )

    def _handle_upload(self, origin: str | None) -> None:
        try:
            filename, destination, uncertain, content_length = self._parse_upload_request()
        except DashboardRequestError as exc:
            self._send_api_error(exc, cors_origin=origin)
            return

        try:
            with tempfile.TemporaryDirectory(prefix="academia-upload-") as temporary_directory:
                source = Path(temporary_directory) / filename
                try:
                    with source.open("xb") as output:
                        remaining = content_length
                        while remaining:
                            chunk = self.rfile.read(min(UPLOAD_CHUNK_BYTES, remaining))
                            if not chunk:
                                raise DashboardRequestError(
                                    400,
                                    "IncompleteUpload",
                                    "upload body ended before Content-Length",
                                )
                            output.write(chunk)
                            remaining -= len(chunk)
                except DashboardRequestError:
                    raise
                except OSError as exc:
                    raise DashboardRequestError(500, "UploadStorageError", "could not stage upload locally") from exc

                import_args = [
                    str(source),
                    "--destination",
                    destination,
                    "--source-label",
                    f"browser-upload:{filename}",
                ]
                if uncertain:
                    import_args.append("--uncertain")
                try:
                    result = _coerce_command_result(self.dashboard.runner("import", [*import_args, "--json"]))
                except DashboardRequestError:
                    raise
                except (CommandTimeoutError, subprocess.TimeoutExpired) as exc:
                    raise DashboardRequestError(504, "CommandTimeout", "academia command timed out") from exc
                except (OSError, TypeError, ValueError) as exc:
                    raise DashboardRequestError(500, "RunnerError", f"could not run academia command: {exc}") from exc

                try:
                    value = json.loads(result.stdout)
                except (json.JSONDecodeError, TypeError):
                    if result.returncode == 0:
                        raise DashboardRequestError(502, "InvalidCLIResponse", "academia command did not return JSON")
                    raise DashboardRequestError(502, "CLIError", "academia command failed without a JSON error")
                self._send_json(200 if result.returncode == 0 else 422, value, cors_origin=origin)
        except DashboardRequestError as exc:
            self._send_api_error(exc, cors_origin=origin)
        except OSError as exc:
            # Do not disclose temporary directory names in transport errors.
            del exc
            self._send_api_error(
                DashboardRequestError(500, "UploadStorageError", "could not stage upload locally"),
                cors_origin=origin,
            )

    def _parse_upload_request(self) -> tuple[str, str, bool, int]:
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().casefold()
        if media_type != "application/octet-stream":
            raise DashboardRequestError(415, "UnsupportedMediaType", "upload requests must use application/octet-stream")
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        if transfer_encoding and transfer_encoding.casefold() != "identity":
            raise DashboardRequestError(400, "UnsupportedTransferEncoding", "upload requests must use a raw Content-Length body")

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
        filename_values = query.get("filename")
        if not filename_values:
            raise DashboardRequestError(400, "MissingFilename", "upload filename is required")
        if len(filename_values) != 1:
            raise DashboardRequestError(400, "InvalidFilename", "upload filename must be supplied once")
        filename = filename_values[0]
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or Path(filename).name != filename
        ):
            raise DashboardRequestError(400, "InvalidFilename", "upload filename must be one safe basename")
        try:
            filename_size = len(filename.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise DashboardRequestError(400, "InvalidFilename", "upload filename must be valid UTF-8") from exc
        if filename_size > MAX_UPLOAD_FILENAME_BYTES:
            raise DashboardRequestError(400, "InvalidFilename", "upload filename is too long")

        destination_values = query.get("destination")
        if not destination_values:
            raise DashboardRequestError(400, "MissingDestination", "upload destination is required")
        if len(destination_values) != 1 or not destination_values[0] or "\x00" in destination_values[0]:
            raise DashboardRequestError(400, "InvalidDestination", "upload destination must be one valid workspace inbox path")
        destination = destination_values[0]

        uncertain_values = query.get("uncertain")
        if uncertain_values is None:
            uncertain = False
        elif len(uncertain_values) == 1 and uncertain_values[0] == "1":
            uncertain = True
        else:
            raise DashboardRequestError(400, "InvalidUncertain", "uncertain must be 1 when supplied")

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise DashboardRequestError(400, "MissingContentLength", "upload request body requires Content-Length")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise DashboardRequestError(400, "InvalidContentLength", "Content-Length must be an integer") from exc
        if length < 0:
            raise DashboardRequestError(400, "InvalidContentLength", "Content-Length must not be negative")
        if length > MAX_UPLOAD_BYTES:
            raise DashboardRequestError(413, "UploadTooLarge", "upload body is too large")
        return filename, destination, uncertain, length

    def _parse_command_request(self) -> tuple[str, list[str]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.casefold().startswith("application/json"):
            raise DashboardRequestError(415, "UnsupportedMediaType", "command requests must use application/json")
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise DashboardRequestError(400, "MissingContentLength", "command request body is required")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise DashboardRequestError(400, "InvalidContentLength", "Content-Length must be an integer") from exc
        if length < 0:
            raise DashboardRequestError(400, "InvalidContentLength", "Content-Length must not be negative")
        if length > MAX_BODY_BYTES:
            raise DashboardRequestError(413, "RequestTooLarge", "command request body is too large")
        try:
            raw = self.rfile.read(length)
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardRequestError(400, "MalformedJSON", "command request body must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise DashboardRequestError(400, "InvalidRequest", "command request must be a JSON object")
        command = value.get("command")
        args = value.get("args")
        if not isinstance(command, str) or not command:
            raise DashboardRequestError(400, "InvalidCommand", "command must be a non-empty string")
        if command not in SAFE_COMMANDS:
            raise DashboardRequestError(400, "CommandNotAllowed", f"dashboard command is not allowed: {command}")
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise DashboardRequestError(400, "InvalidArguments", "args must be an array of strings")
        if len(args) > MAX_ARGUMENTS:
            raise DashboardRequestError(400, "TooManyArguments", f"at most {MAX_ARGUMENTS} command arguments are allowed")
        for arg in args:
            if len(arg) > MAX_ARGUMENT_LENGTH:
                raise DashboardRequestError(400, "ArgumentTooLong", f"command arguments are limited to {MAX_ARGUMENT_LENGTH} characters")
            if "\x00" in arg:
                raise DashboardRequestError(400, "InvalidArguments", "command arguments must not contain NUL bytes")
            option = arg.split("=", 1)[0]
            if option in {"--profile", "--json"}:
                raise DashboardRequestError(400, "ArgumentNotAllowed", f"browser may not supply {option}")
        return command, args

    def _serve_static(self, *, head_only: bool, cors_origin: str | None = None) -> None:
        dist_dir = self.dashboard.dist_dir
        if dist_dir.is_symlink():
            self._send_bytes(
                503,
                _SETUP_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
                cors_origin=cors_origin,
                head_only=head_only,
            )
            return
        root = dist_dir.resolve()
        if not root.is_dir():
            self._send_bytes(
                503,
                _SETUP_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
                cors_origin=cors_origin,
                head_only=head_only,
            )
            return

        requested = urllib.parse.unquote(self.request_path)
        if "\x00" in requested or "\\" in requested:
            self._send_bytes(404, b"Not Found\n", "text/plain; charset=utf-8", cors_origin=cors_origin, head_only=head_only)
            return
        parts = [part for part in requested.split("/") if part not in {"", "."}]
        if ".." in parts:
            self._send_bytes(403, b"Forbidden\n", "text/plain; charset=utf-8", cors_origin=cors_origin, head_only=head_only)
            return
        candidate = (root.joinpath(*parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send_bytes(403, b"Forbidden\n", "text/plain; charset=utf-8", cors_origin=cors_origin, head_only=head_only)
            return

        if not candidate.is_file():
            filename = parts[-1] if parts else ""
            # Asset-like paths should not receive index.html; client-side
            # navigation paths without a file extension use the SPA fallback.
            if (not filename or "." not in filename) and (root / "index.html").is_file():
                candidate = (root / "index.html").resolve()
            else:
                self._send_bytes(404, b"Not Found\n", "text/plain; charset=utf-8", cors_origin=cors_origin, head_only=head_only)
                return
        try:
            candidate.relative_to(root)
            body = candidate.read_bytes()
        except (OSError, ValueError):
            self._send_bytes(404, b"Not Found\n", "text/plain; charset=utf-8", cors_origin=cors_origin, head_only=head_only)
            return
        content_type, _encoding = mimetypes.guess_type(candidate.name)
        self._send_bytes(
            200,
            body,
            content_type or "application/octet-stream",
            cors_origin=cors_origin,
            head_only=head_only,
        )
