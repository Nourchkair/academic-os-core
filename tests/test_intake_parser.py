from __future__ import annotations

from academia_os.intake.parser import parse_announcement


def test_parses_explicit_moved_deadline() -> None:
    candidates, warnings = parse_announcement(
        "My professor moved the Second Essay deadline to November 20.",
        "Fall 2026",
    )
    assert warnings == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.value == "2026-11-20"
    assert candidate.entity_title == "Second Essay"
    assert candidate.confidence == "likely"


def test_prefers_target_date_over_source_date() -> None:
    candidates, _warnings = parse_announcement(
        "Quiz 3 moved from November 19 to November 26.",
        "Fall 2026",
    )
    assert candidates[0].value == "2026-11-26"
    assert candidates[0].entity_title == "Quiz 3"


def test_parses_deadline_for_title_and_year_inference() -> None:
    candidates, _warnings = parse_announcement(
        "The deadline for the Final Essay was moved to December 5.",
        "Fall 2026",
    )
    assert candidates[0].value == "2026-12-05"
    assert candidates[0].entity_title == "Final Essay"


def test_infers_next_year_for_spring_deadline_in_fall_semester() -> None:
    candidates, _warnings = parse_announcement(
        "The Final Essay deadline is now January 15.",
        "Fall 2026",
    )
    assert candidates[0].value == "2027-01-15"


def test_ambiguous_dates_are_not_guessed() -> None:
    candidates, warnings = parse_announcement(
        "The essay may move to Nov. 20 or Nov. 21.",
        "Fall 2026",
    )
    assert warnings
    assert len(candidates) == 1
    assert candidates[0].value is None
    assert "ambiguous_dates" in candidates[0].warnings


def test_non_deadline_text_has_no_candidates() -> None:
    candidates, warnings = parse_announcement("No change today. Have a good weekend.", "Fall 2026")
    assert candidates == []
    assert warnings


def test_quoted_title_is_preserved() -> None:
    candidates, _warnings = parse_announcement(
        'The deadline for "Second Essay" has been extended to November 20.',
        "Fall 2026",
    )
    assert candidates[0].entity_title == "Second Essay"
    assert candidates[0].value == "2026-11-20"
