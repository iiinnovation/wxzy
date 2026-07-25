"""Standard FSRS adapter (P6-T01).

Wraps the maintained `fsrs` package (py-fsrs) and exposes a stable API for
scheduling + algorithm upgrades. Business code must import from this module
instead of the legacy hand-written `fsrs_simple` scheduler.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler, State

# Explicit algorithm identity for ReviewState / ReviewAttempt audit.
# Bump when default parameters, retention, or learning steps change.
ALGORITHM_VERSION = "fsrs-6.3.1"
LIBRARY_NAME = "fsrs"
DESIRED_RETENTION = 0.90
DEFAULT_STABILITY = 1.0
DEFAULT_DIFFICULTY = 5.0

# FSRS learning/relearning steps (seconds) match package defaults.
LEARNING_STEPS = (timedelta(seconds=60), timedelta(seconds=600))
RELEARNING_STEPS = (timedelta(seconds=600),)
MAXIMUM_INTERVAL_DAYS = 36500


def utcnow() -> datetime:
    return datetime.now(UTC)


def _require_utc(value: datetime, *, field_name: str = "datetime") -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    # Normalize to UTC; accept any tz that is exactly UTC.
    converted = value.astimezone(UTC)
    if converted.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return converted.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ScheduleResult:
    due_at: datetime
    stability: float
    difficulty: float
    elapsed_days: float
    scheduled_days: float
    reps: int
    lapses: int
    state: str
    algorithm_version: str = ALGORITHM_VERSION
    step: int | None = None
    library: str = LIBRARY_NAME


@dataclass(frozen=True)
class SchedulerConfig:
    algorithm_version: str = ALGORITHM_VERSION
    desired_retention: float = DESIRED_RETENTION
    enable_fuzzing: bool = False
    maximum_interval: int = MAXIMUM_INTERVAL_DAYS
    learning_steps: tuple[timedelta, ...] = LEARNING_STEPS
    relearning_steps: tuple[timedelta, ...] = RELEARNING_STEPS
    parameters: Sequence[float] | None = None

    def build(self) -> Scheduler:
        kwargs: dict[str, Any] = {
            "desired_retention": self.desired_retention,
            "learning_steps": list(self.learning_steps),
            "relearning_steps": list(self.relearning_steps),
            "maximum_interval": self.maximum_interval,
            "enable_fuzzing": self.enable_fuzzing,
        }
        if self.parameters is not None:
            kwargs["parameters"] = list(self.parameters)
        return Scheduler(**kwargs)


DEFAULT_CONFIG = SchedulerConfig()


def _rating_from_int(rating: int) -> Rating:
    if rating not in {1, 2, 3, 4}:
        raise ValueError("rating must be 1..4")
    return Rating(rating)


def _map_state_to_fsrs(state: str) -> State:
    normalized = (state or "new").strip().lower()
    if normalized in {"new", "learning"}:
        return State.Learning
    if normalized == "review":
        return State.Review
    if normalized == "relearning":
        return State.Relearning
    raise ValueError(f"unsupported review state: {state}")


def _map_state_from_fsrs(state: State, *, previous: str) -> str:
    if state == State.Learning:
        # Preserve "new" only before first successful graduation; after any
        # review the card is at least learning.
        return "learning" if previous == "new" else "learning"
    if state == State.Review:
        return "review"
    if state == State.Relearning:
        return "relearning"
    raise ValueError(f"unsupported FSRS state: {state}")


def _clamp_difficulty(value: float | None) -> float | None:
    if value is None:
        return None
    return max(1.0, min(10.0, float(value)))


def _to_fsrs_card(
    *,
    state: str,
    stability: float | None,
    difficulty: float | None,
    due_at: datetime | None,
    last_reviewed_at: datetime | None,
    step: int | None,
    card_id: int | None = None,
    now: datetime,
) -> FSRSCard:
    fsrs_state = _map_state_to_fsrs(state)
    if fsrs_state == State.Learning:
        card_step: int | None = 0 if step is None else int(step)
    elif fsrs_state == State.Relearning:
        card_step = 0 if step is None else int(step)
    else:
        card_step = None

    # New cards have no measured S/D yet; leave them unset so FSRS applies
    # initial stability/difficulty for the first rating.
    card_stability: float | None
    card_difficulty: float | None
    if state == "new" and last_reviewed_at is None:
        card_stability = None
        card_difficulty = None
    else:
        card_stability = None if stability is None else max(0.0, float(stability))
        card_difficulty = _clamp_difficulty(difficulty)

    return FSRSCard(
        card_id=card_id if card_id is not None else 1,
        state=fsrs_state,
        step=card_step,
        stability=card_stability,
        difficulty=card_difficulty,
        due=due_at or now,
        last_review=last_reviewed_at,
    )


def schedule(
    *,
    rating: int,
    now: datetime | None = None,
    stability: float = DEFAULT_STABILITY,
    difficulty: float = DEFAULT_DIFFICULTY,
    reps: int = 0,
    lapses: int = 0,
    state: str = "new",
    last_reviewed_at: datetime | None = None,
    due_at: datetime | None = None,
    step: int | None = None,
    config: SchedulerConfig | None = None,
    algorithm_version: str | None = None,
) -> ScheduleResult:
    """Schedule the next review with the standard FSRS implementation.

    Rating: 1=Again, 2=Hard, 3=Good, 4=Easy.
    All datetimes must be timezone-aware UTC when provided.
    """
    reviewed_at = _require_utc(now or utcnow(), field_name="now")
    if last_reviewed_at is not None:
        last_reviewed_at = _require_utc(last_reviewed_at, field_name="last_reviewed_at")
        elapsed_days = max((reviewed_at - last_reviewed_at).total_seconds() / 86400.0, 0.0)
    else:
        elapsed_days = 0.0
    if due_at is not None:
        due_at = _require_utc(due_at, field_name="due_at")

    active_config = config or DEFAULT_CONFIG
    scheduler = active_config.build()
    fsrs_card = _to_fsrs_card(
        state=state,
        stability=stability,
        difficulty=difficulty,
        due_at=due_at,
        last_reviewed_at=last_reviewed_at,
        step=step,
        now=reviewed_at,
    )
    updated, _log = scheduler.review_card(
        fsrs_card,
        _rating_from_int(rating),
        review_datetime=reviewed_at,
    )

    next_stability = float(updated.stability if updated.stability is not None else DEFAULT_STABILITY)
    next_difficulty = float(
        _clamp_difficulty(updated.difficulty) if updated.difficulty is not None else DEFAULT_DIFFICULTY
    )
    next_due = _require_utc(updated.due, field_name="due_at")
    scheduled_days = max((next_due - reviewed_at).total_seconds() / 86400.0, 0.0)
    next_state = _map_state_from_fsrs(updated.state, previous=state)

    next_reps = reps
    next_lapses = lapses
    if rating == 1:
        next_lapses = lapses + 1
        next_reps = 0
    else:
        next_reps = reps + 1

    version = algorithm_version or active_config.algorithm_version or ALGORITHM_VERSION
    return ScheduleResult(
        due_at=next_due,
        stability=round(next_stability, 4),
        difficulty=round(next_difficulty, 4),
        elapsed_days=round(elapsed_days, 4),
        scheduled_days=round(scheduled_days, 4),
        reps=next_reps,
        lapses=next_lapses,
        state=next_state,
        algorithm_version=version,
        step=updated.step,
    )


def schedule_to_review_values(
    result: ScheduleResult,
    *,
    rating: int,
    reviewed_at: datetime,
) -> dict[str, Any]:
    """Convert a ScheduleResult into CardReviewState / ReviewStateValues fields."""
    return {
        "due_at": result.due_at,
        "stability": result.stability,
        "difficulty": result.difficulty,
        "elapsed_days": result.elapsed_days,
        "scheduled_days": result.scheduled_days,
        "reps": result.reps,
        "lapses": result.lapses,
        "state": result.state,
        "last_rating": rating,
        "last_reviewed_at": reviewed_at,
        "algorithm_version": result.algorithm_version,
    }


@dataclass(frozen=True)
class UpgradeSample:
    card_key: str
    current_algorithm_version: str
    current_due_at: datetime
    proposed_due_at: datetime
    due_delta_days: float
    current_state: str
    proposed_state: str
    current_stability: float
    proposed_stability: float
    current_difficulty: float
    proposed_difficulty: float
    rating_used: int


@dataclass
class UpgradeDryRunReport:
    from_version: str
    to_version: str
    sample_count: int
    unchanged_due: int
    changed_due: int
    max_abs_delta_days: float
    mean_abs_delta_days: float
    samples: list[UpgradeSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "sample_count": self.sample_count,
            "unchanged_due": self.unchanged_due,
            "changed_due": self.changed_due,
            "max_abs_delta_days": self.max_abs_delta_days,
            "mean_abs_delta_days": self.mean_abs_delta_days,
            "samples": [asdict(s) for s in self.samples],
            "notes": list(self.notes),
            "applied": False,
        }


def _as_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    data: dict[str, Any] = {}
    for key in (
        "card_id",
        "id",
        "external_id",
        "algorithm_version",
        "due_at",
        "stability",
        "difficulty",
        "reps",
        "lapses",
        "state",
        "last_rating",
        "last_reviewed_at",
        "elapsed_days",
        "scheduled_days",
    ):
        if hasattr(row, key):
            data[key] = getattr(row, key)
    return data


def dry_run_algorithm_upgrade(
    rows: Iterable[Any],
    *,
    to_version: str = ALGORITHM_VERSION,
    from_version: str | None = None,
    rating: int = 3,
    now: datetime | None = None,
    config: SchedulerConfig | None = None,
    limit: int = 200,
) -> UpgradeDryRunReport:
    """Compare current due timestamps against a re-schedule under the target algorithm.

    Does not write any database rows. Intended for upgrade planning and rollback
    decisions before a migration is applied.
    """
    reviewed_at = _require_utc(now or utcnow(), field_name="now")
    active_config = config or DEFAULT_CONFIG
    samples: list[UpgradeSample] = []
    source_versions: set[str] = set()
    abs_deltas: list[float] = []

    for index, raw in enumerate(rows):
        if index >= limit:
            break
        row = _as_mapping(raw)
        current_version = str(row.get("algorithm_version") or "unknown")
        if from_version is not None and current_version != from_version:
            continue
        source_versions.add(current_version)
        current_due = row.get("due_at")
        if not isinstance(current_due, datetime):
            raise ValueError("each row requires due_at datetime")
        current_due = _require_utc(current_due, field_name="due_at")
        last_reviewed = row.get("last_reviewed_at")
        if isinstance(last_reviewed, datetime):
            last_reviewed = _require_utc(last_reviewed, field_name="last_reviewed_at")
        else:
            last_reviewed = None
        state = str(row.get("state") or "new")
        stability = float(row.get("stability") if row.get("stability") is not None else DEFAULT_STABILITY)
        difficulty = float(row.get("difficulty") if row.get("difficulty") is not None else DEFAULT_DIFFICULTY)
        reps = int(row.get("reps") or 0)
        lapses = int(row.get("lapses") or 0)
        # Prefer last_rating when available so dry-run mirrors the last observed grade.
        used_rating = int(row.get("last_rating") or rating)
        if used_rating not in {1, 2, 3, 4}:
            used_rating = rating

        proposed = schedule(
            rating=used_rating,
            now=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            reps=reps,
            lapses=lapses,
            state=state,
            last_reviewed_at=last_reviewed,
            due_at=current_due,
            config=active_config,
            algorithm_version=to_version,
        )
        delta_days = (proposed.due_at - current_due).total_seconds() / 86400.0
        abs_deltas.append(abs(delta_days))
        card_key = str(
            row.get("external_id")
            or row.get("card_id")
            or row.get("id")
            or f"row-{index}"
        )
        samples.append(
            UpgradeSample(
                card_key=card_key,
                current_algorithm_version=current_version,
                current_due_at=current_due,
                proposed_due_at=proposed.due_at,
                due_delta_days=round(delta_days, 4),
                current_state=state,
                proposed_state=proposed.state,
                current_stability=stability,
                proposed_stability=proposed.stability,
                current_difficulty=difficulty,
                proposed_difficulty=proposed.difficulty,
                rating_used=used_rating,
            )
        )

    if not samples:
        notes = ["no rows matched dry-run filters"]
        return UpgradeDryRunReport(
            from_version=from_version or ",".join(sorted(source_versions)) or "unknown",
            to_version=to_version,
            sample_count=0,
            unchanged_due=0,
            changed_due=0,
            max_abs_delta_days=0.0,
            mean_abs_delta_days=0.0,
            samples=[],
            notes=notes,
        )

    unchanged = sum(1 for sample in samples if abs(sample.due_delta_days) < 1e-9)
    changed = len(samples) - unchanged
    max_abs = max(abs_deltas) if abs_deltas else 0.0
    mean_abs = (sum(abs_deltas) / len(abs_deltas)) if abs_deltas else 0.0
    notes = [
        "dry-run only; no due_at values were written",
        "fuzzing disabled for deterministic comparison",
        f"desired_retention={active_config.desired_retention}",
    ]
    return UpgradeDryRunReport(
        from_version=from_version or ",".join(sorted(source_versions)),
        to_version=to_version,
        sample_count=len(samples),
        unchanged_due=unchanged,
        changed_due=changed,
        max_abs_delta_days=round(max_abs, 4),
        mean_abs_delta_days=round(mean_abs, 4),
        samples=samples,
        notes=notes,
    )


__all__ = [
    "ALGORITHM_VERSION",
    "DEFAULT_CONFIG",
    "DEFAULT_DIFFICULTY",
    "DEFAULT_STABILITY",
    "DESIRED_RETENTION",
    "LIBRARY_NAME",
    "ScheduleResult",
    "SchedulerConfig",
    "UpgradeDryRunReport",
    "UpgradeSample",
    "dry_run_algorithm_upgrade",
    "schedule",
    "schedule_to_review_values",
    "utcnow",
]
