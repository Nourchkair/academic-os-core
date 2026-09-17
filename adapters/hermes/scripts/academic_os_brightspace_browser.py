#!/usr/bin/env python3
"""Pin and attach Brightspace retrieval to the user's real Chromium profile.

This is intentionally narrower than a general browser launcher. It discovers a
supported Chromium-family browser and its real user-data directory, pins the
selected profile in Hermes state, starts a visible browser with CDP only when
safe, and verifies that the reachable CDP process was launched with that real
profile. It never reads cookie values, passwords, or MFA data, and never uses
Hermes's clean ``chrome-debug`` profile.

The browser tools themselves attach through ``browser.cdp_url`` after the
endpoint is verified. If the browser is already running without CDP, this
script does not terminate it; it attempts a second visible instance and, if
Chrome-family profile locking prevents that, reports the exact manual restart
boundary without touching the existing window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from academia_os.browser import allowed_url

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def state_dir() -> Path:
    return hermes_home() / "state" / "academic_os_brightspace"


def pin_path() -> Path:
    return state_dir() / "browser-profile.json"


@dataclass(frozen=True)
class BrowserSpec:
    name: str
    app: Path
    executable: Path
    user_data_dir: Path



def browser_specs() -> list[BrowserSpec]:
    home = Path.home()
    return [
        BrowserSpec(
            "Google Chrome",
            Path("/Applications/Google Chrome.app"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            home / "Library/Application Support/Google/Chrome",
        ),
        BrowserSpec(
            "Chromium",
            Path("/Applications/Chromium.app"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            home / "Library/Application Support/Chromium",
        ),
        BrowserSpec(
            "Brave",
            Path("/Applications/Brave Browser.app"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            home / "Library/Application Support/BraveSoftware/Brave-Browser",
        ),
        BrowserSpec(
            "Microsoft Edge",
            Path("/Applications/Microsoft Edge.app"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            home / "Library/Application Support/Microsoft Edge",
        ),
    ]


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def local_state(spec: BrowserSpec) -> dict[str, Any]:
    path = spec.user_data_dir / "Local State"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def profile_inventory(spec: BrowserSpec) -> list[dict[str, Any]]:
    state = local_state(spec)
    info_cache = state.get("profile", {}).get("info_cache", {})
    result: list[dict[str, Any]] = []
    if isinstance(info_cache, dict):
        for directory, metadata in sorted(info_cache.items()):
            if not isinstance(metadata, dict):
                metadata = {}
            result.append(
                {
                    "directory": str(directory),
                    "name": str(metadata.get("name") or ""),
                    # Deliberately do not persist or print account email fields.
                    "has_account_metadata": bool(metadata.get("user_name") or metadata.get("gaia_name")),
                    "present": (spec.user_data_dir / str(directory)).is_dir(),
                }
            )
    if result:
        return result
    # Fallback for Chromium-family stores without Local State metadata.
    for candidate in sorted(spec.user_data_dir.glob("*")) if spec.user_data_dir.is_dir() else []:
        if candidate.is_dir() and (candidate / "Preferences").is_file():
            result.append({"directory": candidate.name, "name": "", "has_account_metadata": False, "present": True})
    return result


def running_processes() -> list[dict[str, str]]:
    try:
        output = subprocess.run(
            ["ps", "-axo", "pid=,args="], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return []
    result: list[dict[str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\s+(.*)$", line)
        if not match:
            continue
        pid, args = match.groups()
        if "ps -axo" in args or "/bin/bash -c" in args:
            continue
        result.append({"pid": pid, "args": args})
    return result


def process_for_spec(spec: BrowserSpec, *, port: int | None = None) -> list[dict[str, str]]:
    executable = str(spec.executable)
    marker = str(spec.app).lower()
    matches = []
    for item in running_processes():
        args = item["args"]
        lower = args.lower()
        # Match the app's main executable or its top-level process, not helper
        # renderer processes. The app path is stable even across app updates.
        if executable.lower() in lower or (marker in lower and "helper" not in lower):
            if port is not None and f"--remote-debugging-port={port}" not in args:
                continue
            matches.append(item)
    return matches


def choose_spec() -> tuple[BrowserSpec | None, str | None]:
    specs = [spec for spec in browser_specs() if spec.app.is_dir() and spec.user_data_dir.is_dir()]
    if not specs:
        return None, "No supported Chromium-family browser application with an existing user-data directory was found."
    # Prefer the active browser process. This keeps the pin aligned with the
    # user's real everyday browser rather than an installed but unused app.
    active = [spec for spec in specs if process_for_spec(spec)]
    return (active[0] if active else specs[0]), None


def choose_profile(spec: BrowserSpec) -> tuple[dict[str, Any] | None, str | None]:
    profiles = profile_inventory(spec)
    if not profiles:
        return None, f"No Chromium profile metadata found under {spec.user_data_dir}."
    if len(profiles) == 1:
        return profiles[0], None
    # An explicitly pinned profile wins on subsequent runs.
    if pin_path().is_file():
        try:
            pinned = read_json(pin_path())
            directory = str(pinned.get("profile_directory") or "")
            for profile in profiles:
                if profile["directory"] == directory:
                    return profile, None
        except (OSError, ValueError, TypeError):
            pass
    # If the browser exposes a profile-directory in its process arguments, use
    # that as the active profile evidence. Do not inspect cookies or passwords.
    for process in process_for_spec(spec):
        match = re.search(r"--profile-directory=([^\s]+)", process["args"])
        if match:
            directory = match.group(1).strip('"\'')
            for profile in profiles:
                if profile["directory"] == directory:
                    return profile, None
    # Conservative heuristic for named profiles, only when unique.
    preferred = [
        p for p in profiles
        if any(token in f"{p['directory']} {p['name']}".lower() for token in ("uottawa", "university", "school", "student", "work"))
    ]
    if len(preferred) == 1:
        return preferred[0], None
    return None, "Multiple browser profiles exist and the configured school portal profile could not be identified safely."


def select_and_pin() -> tuple[BrowserSpec | None, dict[str, Any] | None, str | None]:
    spec, error = choose_spec()
    if error or spec is None:
        return None, None, error
    profile, error = choose_profile(spec)
    if error or profile is None:
        return spec, None, error
    payload = {
        "version": 1,
        "browser": spec.name,
        "application": str(spec.app),
        "executable": str(spec.executable),
        "user_data_dir": str(spec.user_data_dir),
        "profile_directory": profile["directory"],
        "profile_name": profile.get("name", ""),
        "real_profile": True,
        "clean_hermes_profile": False,
        "pinned_for": "the configured school portal",
        "pinned_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credentials_read": False,
        "cookies_read": False,
    }
    atomic_write_json(pin_path(), payload)
    return spec, payload, None


def http_json(url: str, timeout: float = 1.5) -> dict[str, Any] | list[Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return None


def cdp_metadata(*, allowed_sites: list[str] | None = None, target_id: str | None = None) -> dict[str, Any] | None:
    version = http_json(f"{CDP_URL}/json/version")
    if not isinstance(version, dict):
        return None
    pages = http_json(f"{CDP_URL}/json")
    safe_pages: list[dict[str, Any]] = []
    sites = [site for site in (allowed_sites or []) if str(site).strip()]
    if isinstance(pages, list) and sites:
        for page in pages[:40]:
            if not isinstance(page, dict):
                continue
            page_identifier = str(page.get("id") or "")
            if target_id and page_identifier != target_id:
                continue
            raw_url = str(page.get("url") or "")
            if not allowed_url(raw_url, sites):
                continue
            raw_title = str(page.get("title") or "")
            # Strip query strings/fragments only after the page has passed the
            # explicit allow-list check. Unrelated tabs are never returned.
            parts = urlsplit(raw_url)
            safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            safe_title = raw_title.split("?", 1)[0].split("#", 1)[0]
            safe_pages.append({
                "id": page_identifier,
                "type": page.get("type"),
                "title": safe_title,
                "url": safe_url,
            })
    return {
        "endpoint": CDP_URL,
        "browser": version.get("Browser"),
        "protocol_version": version.get("Protocol-Version"),
        "page_count": len(safe_pages),
        "pages": safe_pages,
    }


def verify_real_profile(spec: BrowserSpec, pin: dict[str, Any], *, allowed_sites: list[str], target_id: str | None = None) -> dict[str, Any]:
    metadata = cdp_metadata(allowed_sites=allowed_sites, target_id=target_id)
    if metadata is None:
        return {"verified": False, "reason": f"No reachable CDP endpoint at {CDP_URL}."}
    processes = process_for_spec(spec, port=CDP_PORT)
    data_root = str(pin["user_data_dir"])
    profile_dir = str(pin["profile_directory"])
    matching = [
        item for item in processes
        if f"--user-data-dir={data_root}" in item["args"]
        and f"--profile-directory={profile_dir}" in item["args"]
    ]
    if not matching:
        return {
            "verified": False,
            "reason": "CDP is reachable, but no selected-browser process exposes both the pinned real user-data directory and profile-directory.",
            "endpoint": metadata,
            "cdp_processes": processes,
        }
    return {
        "verified": True,
        "browser": spec.name,
        "application": str(spec.app),
        "executable": str(spec.executable),
        "user_data_dir": data_root,
        "profile_directory": profile_dir,
        "profile_name": pin.get("profile_name", ""),
        "real_profile": True,
        "clean_hermes_profile": False,
        "endpoint": metadata,
        "cdp_process_pid": [item["pid"] for item in matching],
    }


def launch_real_browser(spec: BrowserSpec, pin: dict[str, Any], *, allowed_sites: list[str], target_id: str | None = None) -> dict[str, Any]:
    args = [
        str(spec.executable),
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={pin['user_data_dir']}",
        f"--profile-directory={pin['profile_directory']}",
        "--no-default-browser-check",
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return {"launched": False, "error": f"Could not launch {spec.name}: {exc}"}
    for _ in range(20):
        time.sleep(0.5)
        if cdp_metadata(allowed_sites=allowed_sites, target_id=target_id) is not None:
            return {"launched": True, "args": args}
    return {
        "launched": True,
        "args": args,
        "warning": "The visible browser was launched, but CDP did not become reachable; the existing browser process may own the real profile lock.",
    }


def _allowed_sites(args: argparse.Namespace) -> list[str]:
    return list(dict.fromkeys(str(site).strip() for site in getattr(args, "allowed_site", []) if str(site).strip()))


def command_inspect(args: argparse.Namespace) -> int:
    allowed_sites = _allowed_sites(args)
    specs = []
    for spec in browser_specs():
        if not (spec.app.is_dir() or spec.user_data_dir.is_dir()):
            continue
        specs.append({
            "browser": spec.name,
            "application": str(spec.app),
            "application_present": spec.app.is_dir(),
            "executable": str(spec.executable),
            "executable_present": spec.executable.is_file(),
            "user_data_dir": str(spec.user_data_dir),
            "user_data_dir_present": spec.user_data_dir.is_dir(),
            "running": bool(process_for_spec(spec)),
            "profiles": profile_inventory(spec),
        })
    print(json.dumps({"status": "inspection", "cdp": cdp_metadata(allowed_sites=allowed_sites, target_id=args.target_id), "browsers": specs, "pin": read_json(pin_path()) if pin_path().is_file() else None}, indent=2, ensure_ascii=False))
    return 0


def command_ensure(args: argparse.Namespace) -> int:
    allowed_sites = _allowed_sites(args)
    if not allowed_sites:
        print(json.dumps({"status": "error", "error": "At least one --allowed-site is required; browser page metadata is never inspected without an explicit allow-list."}, ensure_ascii=False))
        return 2
    target_id = args.target_id
    spec, pin, error = select_and_pin()
    if error or spec is None or pin is None:
        print(json.dumps({"status": "error", "error": error or "Unable to select a real browser profile."}, ensure_ascii=False))
        return 1
    verified = verify_real_profile(spec, pin, allowed_sites=allowed_sites, target_id=target_id)
    if verified.get("verified"):
        print(json.dumps({"status": "real_profile_ready", **verified}, indent=2, ensure_ascii=False))
        return 0
    if cdp_metadata(allowed_sites=allowed_sites, target_id=target_id) is None:
        launch = launch_real_browser(spec, pin, allowed_sites=allowed_sites, target_id=target_id)
        verified = verify_real_profile(spec, pin, allowed_sites=allowed_sites, target_id=target_id)
        if verified.get("verified"):
            print(json.dumps({"status": "real_profile_ready", "launch": launch, **verified}, indent=2, ensure_ascii=False))
            return 0
        print(json.dumps({"status": "real_profile_not_ready", "pin": pin, "launch": launch, "verification": verified, "manual_boundary": "Do not enter credentials here. If the existing visible browser owns this profile, quit it manually only after saving work, then rerun this command to relaunch the same real profile with CDP."}, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "real_profile_not_ready", "pin": pin, "verification": verified}, indent=2, ensure_ascii=False))
    return 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Pin and verify the real configured school portal Chromium profile")
    sub = root.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Inspect supported browsers/profiles without reading credentials")
    inspect.add_argument("--allowed-site", action="append", default=[], help="Explicit allowed domain; repeat for multiple domains")
    inspect.add_argument("--target-id", help="Optional explicit CDP target/page id")
    inspect.set_defaults(handler=command_inspect)
    ensure = sub.add_parser("ensure", help="Pin, launch if safe, and verify real-profile CDP")
    ensure.add_argument("--allowed-site", action="append", default=[], help="Explicit allowed domain; repeat for multiple domains")
    ensure.add_argument("--target-id", help="Optional explicit CDP target/page id")
    ensure.set_defaults(handler=command_ensure)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
