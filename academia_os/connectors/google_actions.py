"""Review-gated Google Calendar create/update proposals and verification."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from ..actions import ActionProposal, ActionType
from ..activity import ActivityLog
from ..review import ReviewQueue
from ..workflow import ApprovalWorkflow
from .google import GoogleConnector, GoogleConnectorError


def _format_event(event: Mapping[str, Any]) -> str:
    start = event.get("start")
    end = event.get("end")
    start_value = start.get("dateTime") if isinstance(start, dict) else ""
    end_value = end.get("dateTime") if isinstance(end, dict) else ""
    lines = [str(event.get("summary") or "Untitled event"), f"{start_value} – {end_value}"]
    if event.get("location"):
        lines.append(f"Location: {event['location']}")
    if event.get("description"):
        lines.append(f"Description: {event['description']}")
    return "\n".join(lines)


def _event_for_create(event: Mapping[str, Any]) -> dict[str, Any]:
    normalized = GoogleConnector.validate_calendar_event(event)
    return {
        "summary": normalized["summary"],
        "start": {"dateTime": normalized["start"]},
        "end": {"dateTime": normalized["end"]},
        **({"location": normalized["location"]} if normalized.get("location") else {}),
        **({"description": normalized["description"]} if normalized.get("description") else {}),
    }


def propose_calendar_create(workflow: ApprovalWorkflow, connector: GoogleConnector, event: Mapping[str, Any]) -> tuple[ActionProposal, Any]:
    desired = _event_for_create(event)
    matches = connector.calendar_find_duplicates(desired)
    if matches:
        first = matches[0]
        raise GoogleConnectorError(
            "A matching Google Calendar event already exists; no proposal was created "
            f"(event id {first.get('id') or 'unknown'})."
        )
    title = f"Create Google Calendar event: {desired['summary']}"
    details = {
        "calendar_action": "create",
        "calendar_id": "primary",
        "event": desired,
        "before": "No matching event found in the primary calendar.",
        "after": _format_event({
            "summary": desired["summary"],
            "start": desired["start"],
            "end": desired["end"],
            "location": desired.get("location"),
            "description": desired.get("description"),
        }),
        "effects": [
            "Create exactly one event in the connected Google account's primary calendar.",
            "Recheck for a matching event immediately before creating it.",
            "Read the event back from Google and verify the exact title and time after creation.",
        ],
        "duplicate_check": {"checked_at": datetime.now(timezone.utc).isoformat(), "matches": 0},
    }
    return workflow.propose(
        action_type=ActionType.CALENDAR_CHANGE,
        title=title,
        details=details,
        review_kind="action_approval",
        review_details={"calendar_action": "create", "proposal_details": {"action_type": ActionType.CALENDAR_CHANGE.value, **details}},
    )


def propose_calendar_update(
    workflow: ApprovalWorkflow,
    connector: GoogleConnector,
    *,
    event_id: str,
    patch: Mapping[str, Any],
) -> tuple[ActionProposal, Any]:
    current = connector.calendar_get(event_id)
    if current is None:
        raise GoogleConnectorError("Google Calendar event was not found; no proposal was created")
    if not isinstance(patch, Mapping) or not patch or set(patch) - {"summary", "start", "end", "location", "description"}:
        raise GoogleConnectorError("provide one or more supported event fields to edit")
    before = {
        "summary": current.get("summary") or "Untitled event",
        "start": current.get("start") if isinstance(current.get("start"), dict) else {},
        "end": current.get("end") if isinstance(current.get("end"), dict) else {},
        "location": current.get("location"),
        "description": current.get("description"),
    }
    target = {
        "summary": patch.get("summary", before["summary"]),
        "start": patch.get("start", before["start"].get("dateTime")),
        "end": patch.get("end", before["end"].get("dateTime")),
        "location": patch.get("location", before["location"]),
        "description": patch.get("description", before["description"]),
    }
    if not isinstance(target["start"], str) or not isinstance(target["end"], str):
        raise GoogleConnectorError("only timed Google Calendar events can be edited through this proposal")
    normalized_target = GoogleConnector.validate_calendar_event(target)
    after_event = {
        "summary": normalized_target["summary"],
        "start": {"dateTime": normalized_target["start"]},
        "end": {"dateTime": normalized_target["end"]},
        **({"location": normalized_target["location"]} if normalized_target.get("location") else {}),
        **({"description": normalized_target["description"]} if normalized_target.get("description") else {}),
    }
    patch_fields = dict(patch)
    if "start" in patch_fields:
        patch_fields["start"] = normalized_target["start"]
    if "end" in patch_fields:
        patch_fields["end"] = normalized_target["end"]
    if "summary" in patch_fields:
        patch_fields["summary"] = normalized_target["summary"]
    if "location" in patch_fields and normalized_target.get("location") is not None:
        patch_fields["location"] = normalized_target.get("location") or ""
    if "description" in patch_fields and normalized_target.get("description") is not None:
        patch_fields["description"] = normalized_target.get("description") or ""
    matches = connector.calendar_find_duplicates(after_event, exclude_event_id=event_id)
    if matches:
        first = matches[0]
        raise GoogleConnectorError(
            "The proposed edit would duplicate another Google Calendar event; no proposal was created "
            f"(event id {first.get('id') or 'unknown'})."
        )
    etag = current.get("etag")
    if not isinstance(etag, str) or not etag:
        raise GoogleConnectorError("Google did not return an event version; no edit proposal was created")
    title = f"Edit Google Calendar event: {normalized_target['summary']}"
    details = {
        "calendar_action": "update",
        "calendar_id": "primary",
        "event_id": event_id,
        "expected_etag": etag,
        "patch": patch_fields,
        "before": _format_event(before),
        "after": _format_event(after_event),
        "effects": [
            "Update only the reviewed fields of this primary-calendar event.",
            "Refuse to overwrite the event if Google reports it changed since this proposal was prepared.",
            "Read the event back from Google and verify the reviewed fields after editing.",
        ],
        "duplicate_check": {"checked_at": datetime.now(timezone.utc).isoformat(), "matches": 0},
    }
    return workflow.propose(
        action_type=ActionType.CALENDAR_CHANGE,
        title=title,
        details=details,
        review_kind="action_approval",
        review_details={"calendar_action": "update", "proposal_details": {"action_type": ActionType.CALENDAR_CHANGE.value, **details}},
    )


def _to_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _event_matches(expected: Mapping[str, Any], actual: Mapping[str, Any], *, fields: set[str] | None = None) -> bool:
    check = fields or {"summary", "start", "end", "location", "description"}
    for field in check:
        wanted = expected.get(field)
        if field in {"start", "end"}:
            wanted_value = wanted.get("dateTime") if isinstance(wanted, dict) else wanted
            actual_part = actual.get(field) if isinstance(actual.get(field), dict) else {}
            actual_value = actual_part.get("dateTime")
            wanted_time = _to_datetime(wanted_value)
            actual_time = _to_datetime(actual_value)
            if wanted_time is None or actual_time is None or wanted_time != actual_time:
                return False
        elif field in {"location", "description"}:
            if str(wanted or "") != str(actual.get(field) or ""):
                return False
        elif actual.get(field) != wanted:
            return False
    return True


def execute_calendar_change(proposal: ActionProposal, connector: GoogleConnector) -> dict[str, Any]:
    if proposal.action_type != ActionType.CALENDAR_CHANGE.value:
        raise GoogleConnectorError("proposal is not a Google Calendar change")
    details = proposal.details
    action = details.get("calendar_action")
    if action == "create":
        event = details.get("event")
        operation = details.get("operation") if isinstance(details.get("operation"), dict) else {}
        operation_id = operation.get("id")
        if not isinstance(event, dict) or not isinstance(operation_id, str):
            raise GoogleConnectorError("calendar create proposal is incomplete")
        event_id = hashlib.sha256(f"academia-google-calendar:{operation_id}".encode("utf-8")).hexdigest()
        existing = connector.calendar_get(event_id, missing_ok=True)
        if existing is not None:
            if not _event_matches(event, existing):
                raise GoogleConnectorError("the operation's Google Calendar event id exists with different details; refusing to overwrite it")
            return {"verified": True, "event_id": event_id, "already_applied": True, "summary": existing.get("summary")}
        duplicates = connector.calendar_find_duplicates(event)
        if duplicates:
            raise GoogleConnectorError(f"a matching Google Calendar event already exists (id {duplicates[0].get('id') or 'unknown'}); no event was created")
        try:
            connector.calendar_create(event, event_id=event_id)
        except GoogleConnectorError:
            # A lost response or process restart after Google's commit is safe:
            # deterministic event ids let us verify the prior write without
            # creating a second event.
            recovered = connector.calendar_get(event_id, missing_ok=True)
            if recovered is None or not _event_matches(event, recovered):
                raise
        verified_event = connector.calendar_get(event_id)
        if verified_event is None or not _event_matches(event, verified_event):
            raise GoogleConnectorError("Google Calendar create completed but read-back verification did not match")
        return {"verified": True, "event_id": event_id, "already_applied": False, "summary": verified_event.get("summary")}

    if action == "update":
        event_id = details.get("event_id")
        expected_etag = details.get("expected_etag")
        patch = details.get("patch")
        if not isinstance(event_id, str) or not isinstance(expected_etag, str) or not isinstance(patch, dict) or not patch:
            raise GoogleConnectorError("calendar update proposal is incomplete")
        current = connector.calendar_get(event_id)
        if current is None:
            raise GoogleConnectorError("the approved Google Calendar event no longer exists")
        if _event_matches(patch, current, fields=set(patch)):
            return {"verified": True, "event_id": event_id, "already_applied": True, "summary": current.get("summary")}
        if current.get("etag") != expected_etag:
            raise GoogleConnectorError("the Google Calendar event changed after review; no update was applied")
        target = {
            "summary": patch.get("summary", current.get("summary")),
            "start": patch.get("start", (current.get("start") or {}).get("dateTime") if isinstance(current.get("start"), dict) else None),
            "end": patch.get("end", (current.get("end") or {}).get("dateTime") if isinstance(current.get("end"), dict) else None),
            "location": patch.get("location", current.get("location")),
            "description": patch.get("description", current.get("description")),
        }
        if not isinstance(target["start"], str) or not isinstance(target["end"], str):
            raise GoogleConnectorError("only timed Google Calendar events can be edited through this action")
        normalized = GoogleConnector.validate_calendar_event(target)
        desired = {
            "summary": normalized["summary"],
            "start": {"dateTime": normalized["start"]},
            "end": {"dateTime": normalized["end"]},
            **({"location": normalized["location"]} if normalized.get("location") else {}),
            **({"description": normalized["description"]} if normalized.get("description") else {}),
        }
        duplicates = connector.calendar_find_duplicates(desired, exclude_event_id=event_id)
        if duplicates:
            raise GoogleConnectorError(f"the approved edit would duplicate another event (id {duplicates[0].get('id') or 'unknown'}); no update was applied")
        connector.calendar_patch(event_id, patch, etag=expected_etag)
        verified_event = connector.calendar_get(event_id)
        if verified_event is None or not _event_matches(patch, verified_event, fields=set(patch)):
            raise GoogleConnectorError("Google Calendar update completed but read-back verification did not match")
        return {"verified": True, "event_id": event_id, "already_applied": False, "summary": verified_event.get("summary")}

    raise GoogleConnectorError("unsupported Google Calendar action")
