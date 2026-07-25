"""P6-T01: standard FSRS adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.learning import fsrs_adapter
from app.learning.fsrs_adapter import (
    ALGORITHM_VERSION,
    DESIRED_RETENTION,
    dry_run_algorithm_upgrade,
    schedule,
    utcnow,
)

NOW = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)


def test_algorithm_version_and_retention() -> None:
    assert ALGORITHM_VERSION.startswith("fsrs-")
    assert DESIRED_RETENTION == 0.90
    assert utcnow().tzinfo is not None


@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_schedule_returns_utc_due(rating: int) -> None:
    result = schedule(rating=rating, now=NOW)
    assert result.due_at.tzinfo is not None
    assert result.due_at.utcoffset() == timedelta(0)
    assert result.due_at > NOW
    assert result.algorithm_version == ALGORITHM_VERSION
    assert 1.0 <= result.difficulty <= 10.0
    assert result.stability >= 0.0


def test_four_ratings_produce_distinct_due() -> None:
    dues = {
        rating: schedule(rating=rating, now=NOW, state="new").due_at
        for rating in (1, 2, 3, 4)
    }
    # Again < Hard < Good for first learning steps; Easy graduates far later.
    assert dues[1] < dues[2] < dues[3] < dues[4]
    easy_days = (dues[4] - NOW).total_seconds() / 86400.0
    again_days = (dues[1] - NOW).total_seconds() / 86400.0
    assert easy_days - again_days > 1.0


def test_review_state_four_ratings_distinct() -> None:
    base = dict(
        now=NOW,
        stability=5.0,
        difficulty=5.0,
        reps=3,
        lapses=0,
        state="review",
        last_reviewed_at=NOW - timedelta(days=5),
        due_at=NOW,
    )
    dues = {rating: schedule(rating=rating, **base).due_at for rating in (1, 2, 3, 4)}
    assert dues[1] < dues[2] < dues[3] < dues[4]


def test_rejects_non_utc_now() -> None:
    naive = datetime(2026, 7, 25, 8, 0)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        schedule(rating=3, now=naive)


def test_rejects_invalid_rating() -> None:
    with pytest.raises(ValueError, match="rating must be 1..4"):
        schedule(rating=0, now=NOW)


def test_elapsed_days_from_last_review() -> None:
    result = schedule(
        rating=3,
        now=NOW,
        last_reviewed_at=NOW - timedelta(days=2, hours=12),
        state="review",
        stability=4.0,
        difficulty=5.0,
        reps=2,
    )
    assert result.elapsed_days == 2.5


def test_again_increments_lapses_and_resets_reps() -> None:
    result = schedule(
        rating=1,
        now=NOW,
        stability=8.0,
        difficulty=4.0,
        reps=5,
        lapses=1,
        state="review",
        last_reviewed_at=NOW - timedelta(days=3),
    )
    assert result.lapses == 2
    assert result.reps == 0
    assert result.state == "relearning"


def test_dry_run_upgrade_does_not_apply() -> None:
    rows = [
        {
            "card_id": 1,
            "algorithm_version": "fsrs-v1",
            "due_at": NOW + timedelta(days=2),
            "stability": 3.0,
            "difficulty": 5.0,
            "reps": 2,
            "lapses": 0,
            "state": "review",
            "last_rating": 3,
            "last_reviewed_at": NOW - timedelta(days=2),
        },
        {
            "card_id": 2,
            "algorithm_version": "fsrs-v1",
            "due_at": NOW + timedelta(hours=1),
            "stability": 1.0,
            "difficulty": 5.0,
            "reps": 0,
            "lapses": 0,
            "state": "new",
            "last_rating": None,
            "last_reviewed_at": None,
        },
    ]
    report = dry_run_algorithm_upgrade(rows, from_version="fsrs-v1", now=NOW, rating=3)
    assert report.sample_count == 2
    assert report.to_version == ALGORITHM_VERSION
    assert report.from_version == "fsrs-v1"
    payload = report.to_dict()
    assert payload["applied"] is False
    assert payload["sample_count"] == 2
    assert "dry-run only" in " ".join(payload["notes"])
    # dues may change; report must quantify the delta without mutating input
    assert rows[0]["due_at"] == NOW + timedelta(days=2)
    assert report.max_abs_delta_days >= 0.0


def test_business_modules_do_not_import_fsrs_simple() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "fsrs_simple.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "fsrs_simple" in text:
            # adapter dry-run may mention the name in docs; imports are forbidden
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "import" in stripped and "fsrs_simple" in stripped:
                    offenders.append(f"{path.relative_to(root.parent)}: {stripped}")
    assert offenders == []


def test_adapter_is_not_fsrs_simple_module() -> None:
    assert "fsrs_simple" not in fsrs_adapter.__file__
    assert fsrs_adapter.schedule is not None
