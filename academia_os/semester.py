from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AcademicCalendar:
    """Month-based academic calendar policy that can be customized per institution."""

    term_start_months: tuple[tuple[str, int], ...] = (
        ("Winter", 1),
        ("Spring", 5),
        ("Summer", 7),
        ("Fall", 9),
    )

    def semester_for(self, value: date) -> str:
        selected_term, selected_month = self.term_start_months[0]
        for term, start_month in self.term_start_months:
            if start_month <= value.month and start_month >= selected_month:
                selected_term, selected_month = term, start_month
        if value.month < selected_month:
            prior = self.term_start_months[-1][0]
            return f"{prior} {value.year - 1}"
        return f"{selected_term} {value.year}"


def resolve_current_semester(when: datetime | date | None = None, timezone_name: str = "UTC", calendar: AcademicCalendar | None = None) -> str:
    """Resolve an actual semester identifier; never persist a human placeholder."""

    value = when
    if value is None:
        try:
            value = datetime.now(ZoneInfo(timezone_name))
        except Exception:
            value = datetime.now().astimezone()
    if isinstance(value, datetime):
        value = value.date()
    return (calendar or AcademicCalendar()).semester_for(value)


def semester_suggestions(when: datetime | date | None = None, timezone_name: str = "UTC") -> list[str]:
    current = resolve_current_semester(when, timezone_name)
    year = int(current.rsplit(" ", 1)[1])
    term = current.rsplit(" ", 1)[0]
    ordered = ["Winter", "Spring", "Summer", "Fall"]
    index = ordered.index(term)
    suggestions = [current]
    for offset in range(1, 5):
        position = index + offset
        suggestions.append(f"{ordered[position % len(ordered)]} {year + position // len(ordered)}")
    return suggestions
