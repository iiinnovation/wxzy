"""Lightweight FSRS-like scheduler for MVP.

Not a full FSRS-4.5 port. Provides stable, algorithm_versioned scheduling so we can
upgrade later without discarding review logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScheduleResult:
    due_at: datetime
    stability: float
    difficulty: float
    elapsed_days: float
    scheduled_days: float
    reps: int
    lapses: int
    state: str


# rating: 1=Again, 2=Hard, 3=Good, 4=Easy
def schedule(
    *,
    rating: int,
    now: datetime | None = None,
    stability: float = 1.0,
    difficulty: float = 5.0,
    reps: int = 0,
    lapses: int = 0,
    state: str = "new",
    last_reviewed_at: datetime | None = None,
) -> ScheduleResult:
    now = now or utcnow()
    if last_reviewed_at is not None:
        elapsed_days = max((now - last_reviewed_at).total_seconds() / 86400.0, 0.0)
    else:
        elapsed_days = 0.0

    d = max(1.0, min(10.0, difficulty))
    s = max(0.1, stability)

    if rating == 1:  # Again
        lapses += 1
        reps = 0
        s = max(0.3, s * 0.5)
        d = min(10.0, d + 0.8)
        scheduled_days = 0.01  # ~15 min for learning
        new_state = "relearning" if state != "new" else "learning"
    elif rating == 2:  # Hard
        reps += 1
        s = max(0.5, s * 1.2)
        d = min(10.0, d + 0.15)
        scheduled_days = max(0.5, s * 0.8)
        new_state = "review"
    elif rating == 3:  # Good
        reps += 1
        s = max(1.0, s * 1.8 if reps > 1 else 1.0)
        d = max(1.0, d - 0.05)
        if state in ("new", "learning", "relearning"):
            scheduled_days = 1.0 if reps == 1 else max(1.0, s)
        else:
            scheduled_days = max(1.0, s)
        new_state = "review"
    elif rating == 4:  # Easy
        reps += 1
        s = max(1.5, s * 2.3 if reps > 1 else 2.5)
        d = max(1.0, d - 0.2)
        scheduled_days = max(2.0, s * 1.3)
        new_state = "review"
    else:
        raise ValueError("rating must be 1..4")

    # difficulty slightly dampens interval
    scheduled_days = scheduled_days * (11.0 - d) / 10.0
    scheduled_days = max(0.01, min(scheduled_days, 365.0))
    due_at = now + timedelta(days=scheduled_days)
    return ScheduleResult(
        due_at=due_at,
        stability=round(s, 4),
        difficulty=round(d, 4),
        elapsed_days=round(elapsed_days, 4),
        scheduled_days=round(scheduled_days, 4),
        reps=reps,
        lapses=lapses,
        state=new_state,
    )
