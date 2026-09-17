"""Browser-neutral acquisition contracts.

The core accepts normalized metadata and explicit user-selected browser sources.
Only capability declarations and safe allow-list checks live here; no adapter is
allowed to read passwords, cookies, MFA codes, or hidden session tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class BrowserAcquisition:
    source_type: str
    browser: str
    source_url: str
    acquired_at: str
    original_file: str | None = None
    profile_label: str | None = None


@dataclass(frozen=True)
class BrowserCapability:
    browser: str
    status: str
    mode: str
    description: str


class BrowserAdapter:
    browser = "unknown"

    def capability(self) -> BrowserCapability:
        raise NotImplementedError

    def acquire_explicit(self, *, source_url: str, original_file: str | None = None) -> BrowserAcquisition:
        raise NotImplementedError("browser acquisition requires an explicit user action and a concrete adapter")


def allowed_url(url: str, allowed_sites: list[str]) -> bool:
    """Return whether a URL host matches an explicit exact/subdomain allow-list."""
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    if not hostname or not allowed_sites:
        return False
    for site in allowed_sites:
        candidate = site.lower().strip().removeprefix("https://").removeprefix("http://").split("/", 1)[0].rstrip(".")
        if hostname == candidate or hostname.endswith("." + candidate):
            return True
    return False


def normalized_browser_metadata(*, browser: str, source_url: str, acquired_at: str, original_file: str | None = None, profile_label: str | None = None) -> dict[str, str | None]:
    return {
        "source_type": "browser",
        "browser": browser,
        "source_url": source_url,
        "acquired_at": acquired_at,
        "original_file": original_file,
        "profile_label": profile_label,
    }
