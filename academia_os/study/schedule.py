"""Place advisory study-plan blocks into concrete free time windows."""
from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


def _parse_time(value: str) -> time:
    try:
        hour, minute = value.split(':', 1)
        parsed = time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ValueError('time must use HH:MM') from exc
    if parsed.strftime('%H:%M') != value:
        raise ValueError('time must use HH:MM')
    return parsed


def _event_interval(event: Mapping[str, Any], zone: ZoneInfo) -> tuple[datetime, datetime] | None:
    start = event.get('start') if isinstance(event.get('start'), Mapping) else {}
    end = event.get('end') if isinstance(event.get('end'), Mapping) else {}
    start_value = start.get('dateTime') or start.get('date')
    end_value = end.get('dateTime') or end.get('date')
    if not start_value or not end_value:
        return None
    try:
        start_dt = datetime.fromisoformat(str(start_value).replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(str(end_value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if 'date' in start and 'T' not in str(start_value):
        start_dt = datetime.combine(start_dt.date(), time(0, 0), zone)
    elif start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=zone)
    if 'date' in end and 'T' not in str(end_value):
        end_dt = datetime.combine(end_dt.date(), time(0, 0), zone)
    elif end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=zone)
    return start_dt.astimezone(zone), end_dt.astimezone(zone)


def _subtract(intervals: list[tuple[datetime, datetime]], busy: tuple[datetime, datetime]) -> list[tuple[datetime, datetime]]:
    result = []
    busy_start, busy_end = busy
    for start, end in intervals:
        if busy_end <= start or busy_start >= end:
            result.append((start, end))
            continue
        if start < busy_start:
            result.append((start, min(busy_start, end)))
        if busy_end < end:
            result.append((max(busy_end, start), end))
    return [(start, end) for start, end in result if end - start >= timedelta(minutes=5)]


def _ceil_five(value: datetime) -> datetime:
    minute = ((value.minute + 4) // 5) * 5
    if minute >= 60:
        return (value + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return value.replace(minute=minute, second=0, microsecond=0)


def _chunks(blocks: Iterable[Mapping[str, Any]], block_minutes: int) -> list[dict[str, Any]]:
    chunks = []
    for block in blocks:
        remaining = int(block['minutes'])
        while remaining > 0:
            minutes = min(block_minutes, remaining)
            chunks.append({**block, 'minutes': minutes})
            remaining -= minutes
    return chunks


def _summary(course: Mapping[str, Any]) -> str:
    code = str(course.get('code') or course.get('id') or 'Course')
    return f"{code} study block"


def schedule_blocks(
    config: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    minutes: int = 120,
    days: int = 7,
    start_time: str = '09:00',
    end_time: str = '21:00',
    block_minutes: int = 45,
    course_id: str | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    calendar_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 5 <= minutes <= 600:
        raise ValueError('study time must be between 5 and 600 minutes')
    if not 1 <= days <= 14:
        raise ValueError('schedule window must be 1–14 days')
    if not 15 <= block_minutes <= 120:
        raise ValueError('study block length must be 15–120 minutes')
    start_clock, end_clock = _parse_time(start_time), _parse_time(end_time)
    if start_clock >= end_clock:
        raise ValueError('start time must be before end time')
    zone = ZoneInfo(str(config['academic']['timezone']))
    current = (now or datetime.now(zone)).astimezone(zone)
    from .cli import plan

    planned = plan(config, snapshot, minutes, course_id, today=current.date())
    courses = {str(course.get('id')): course for course in snapshot.get('courses', [])}
    chunks = _chunks(planned['blocks'], block_minutes)
    busy = []
    for event in calendar_events or []:
        interval = _event_interval(event, zone)
        if interval:
            busy.append(interval)
    day = current.date()
    if current.time() >= end_clock:
        day = day + timedelta(days=1)
    free: list[tuple[datetime, datetime]] = []
    for offset in range(days):
        selected = day + timedelta(days=offset)
        window_start = datetime.combine(selected, start_clock, zone)
        window_end = datetime.combine(selected, end_clock, zone)
        if selected == current.date():
            window_start = _ceil_five(max(window_start, current + timedelta(minutes=5)))
        intervals = [(window_start, window_end)] if window_start < window_end else []
        for interval in busy:
            intervals = _subtract(intervals, interval)
        free.extend(intervals)
    blocks, unscheduled = [], []
    for chunk in chunks:
        required = timedelta(minutes=int(chunk['minutes']))
        placed = False
        for index, (slot_start, slot_end) in enumerate(free):
            if slot_end - slot_start >= required:
                start_dt = _ceil_five(slot_start)
                end_dt = start_dt + required
                course = courses.get(str(chunk['course_id']), {})
                block = {
                    'id': hashlib.sha256(f"{start_dt.isoformat()}|{chunk['course_id']}|{chunk['title']}".encode()).hexdigest()[:16],
                    'course_id': chunk['course_id'],
                    'course_name': course.get('name'),
                    'title': chunk['title'],
                    'reason': chunk['reason'],
                    'action': chunk['action'],
                    'minutes': chunk['minutes'],
                    'start': start_dt.isoformat(),
                    'end': end_dt.isoformat(),
                    'summary': _summary(course),
                    'description': f"Advisory study block from Academia OS. Focus: {chunk['title']}. Reason: {chunk['reason']}. Confirm before adding it to your calendar.",
                    'source': 'academia_study_schedule',
                }
                blocks.append(block)
                free[index] = (_ceil_five(end_dt + timedelta(minutes=5)), slot_end)
                placed = True
                break
        if not placed:
            unscheduled.append(chunk)
    return {
        'schema_version': 1,
        'generated_at': current.isoformat(),
        'timezone': str(zone),
        'window': {'start_date': day.isoformat(), 'days': days, 'start_time': start_time, 'end_time': end_time},
        'minutes_requested': minutes,
        'minutes_scheduled': sum(block['minutes'] for block in blocks),
        'blocks': blocks,
        'unscheduled': unscheduled,
        'calendar_checked': calendar_events is not None,
        'calendar_error': calendar_error,
        'advisory': True,
        'calendar_changes': False,
        'note': 'Blocks are suggestions placed around known calendar events. Nothing is added to Google Calendar until the student approves a Review proposal and executes it separately.',
    }
