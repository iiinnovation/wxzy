from datetime import UTC, datetime, timedelta

import pytest

from app.fsrs_simple import schedule

NOW = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rating", "expected_state", "expected_reps", "expected_lapses"),
    [
        (1, "learning", 0, 1),
        (2, "review", 1, 0),
        (3, "review", 1, 0),
        (4, "review", 1, 0),
    ],
)
def test_schedule_handles_all_ratings(
    rating: int,
    expected_state: str,
    expected_reps: int,
    expected_lapses: int,
) -> None:
    result = schedule(rating=rating, now=NOW)

    assert result.state == expected_state
    assert result.reps == expected_reps
    assert result.lapses == expected_lapses
    assert result.due_at > NOW
    assert result.due_at.tzinfo is not None


def test_schedule_records_elapsed_days() -> None:
    result = schedule(rating=3, now=NOW, last_reviewed_at=NOW - timedelta(days=2))

    assert result.elapsed_days == 2.0


def test_schedule_rejects_unknown_rating() -> None:
    with pytest.raises(ValueError, match="rating must be 1..4"):
        schedule(rating=0, now=NOW)
