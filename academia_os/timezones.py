from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import available_timezones

COMMON_TIMEZONES = [
    "UTC", "America/New_York", "America/Toronto", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Vancouver", "America/Edmonton", "America/Halifax", "America/St_Johns", "Europe/London", "Europe/Paris",
    "Europe/Berlin", "Asia/Dubai", "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
]
FRIENDLY_TIMEZONES = {
    "UTC": "UTC (Coordinated Universal Time)", "America/New_York": "Eastern Time — New York / Toronto", "America/Toronto": "Eastern Time — Toronto",
    "America/Chicago": "Central Time — Chicago", "America/Denver": "Mountain Time — Denver", "America/Los_Angeles": "Pacific Time — Los Angeles / Vancouver",
    "America/Vancouver": "Pacific Time — Vancouver", "America/Edmonton": "Mountain Time — Edmonton", "America/Halifax": "Atlantic Time — Halifax",
    "America/St_Johns": "Newfoundland Time — St. John's", "Europe/London": "United Kingdom / Ireland — London", "Europe/Paris": "Central Europe — Paris / Berlin",
    "Europe/Berlin": "Central Europe — Berlin", "Asia/Dubai": "Gulf Time — Dubai", "Asia/Kolkata": "India — Kolkata", "Asia/Singapore": "Singapore / Malaysia",
    "Asia/Tokyo": "Japan — Tokyo", "Australia/Sydney": "Australia East — Sydney",
}


def detect_local_timezone(localtime_path: Path | None = None) -> str:
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz and env_tz in available_timezones():
        return env_tz
    localtime = (localtime_path or Path("/etc/localtime")).expanduser()
    try:
        resolved = localtime.resolve()
        parts = resolved.parts
        if "zoneinfo" in parts:
            candidate = "/".join(parts[parts.index("zoneinfo") + 1 :])
            if candidate in available_timezones():
                return candidate
    except OSError:
        pass
    return ""


def timezone_choices(filter_text: str = "") -> list[str]:
    query = filter_text.strip().lower()
    values = sorted(available_timezones())
    if not query:
        preferred = [item for item in COMMON_TIMEZONES if item in values]
        return preferred + [item for item in values if item not in preferred]
    return [item for item in values if query in item.lower()]


def friendly_timezone_label(timezone_name: str) -> str:
    return FRIENDLY_TIMEZONES.get(timezone_name, timezone_name)


def friendly_timezone_choices() -> list[str]:
    values = [friendly_timezone_label(item) for item in COMMON_TIMEZONES if item in available_timezones()]
    return values + ["Other time zone…"]


def timezone_from_friendly_label(label: str) -> str:
    for timezone_name, friendly in FRIENDLY_TIMEZONES.items():
        if label == friendly:
            return timezone_name
    return label.strip()
