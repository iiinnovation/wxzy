from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..catalog.models import Book, Card, CardSource, Chapter, DocumentChunk
from ..identity.models import LearningProfile, User
from .coach import build_repair_suggestions
from .models import (
    CardEnrollment,
    CardReviewState,
    DailyPlan,
    DailyPlanItem,
    ReviewAttempt,
    StudySession,
)
from .schemas import EnrollmentStatus
from .services import (
    _require_aware_utc,
    list_due_review_states,
    list_queued_enrollments,
)

GENERATION_VERSION = "daily-plan-v1"
DEFAULT_REVIEW_SECONDS = 45
DEFAULT_NEW_SECONDS = 90
DEFAULT_WEAK_SECONDS = 60
MIN_HISTORY_FOR_ESTIMATE = 5
RESPONSE_HISTORY_LIMIT = 50
MIXED_WEEKLY_LIMIT = 3


class DailyPlanError(RuntimeError):
    pass


class DailyPlanReferenceError(DailyPlanError):
    pass


class DailyPlanStateError(DailyPlanError):
    pass


@dataclass(frozen=True)
class _Candidate:
    enrollment_id: int
    card_id: int
    item_type: str
    reason_code: str
    reason_detail: str | None
    estimated_seconds: int
    sort_key: tuple


def _zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise DailyPlanStateError(f"invalid owner timezone: {name}") from exc


def _local_date(now: datetime, timezone_name: str) -> date:
    return _require_aware_utc(now).astimezone(_zoneinfo(timezone_name)).date()


def _weekday_index(local_day: date) -> int:
    # Monday=0 ... Sunday=6 to match study_days contract.
    return local_day.weekday()


def _is_study_day(study_days: list[bool], local_day: date) -> bool:
    if len(study_days) != 7:
        return True
    return bool(study_days[_weekday_index(local_day)])


def _median(values: list[int]) -> int:
    if not values:
        return DEFAULT_REVIEW_SECONDS
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _estimate_seconds(
    db: Session,
    *,
    user_id: int,
    kind: str,
) -> tuple[int, bool]:
    """Return (seconds, used_default). kind in review|new|weak."""
    rows = list(
        db.scalars(
            select(ReviewAttempt.response_ms)
            .where(ReviewAttempt.user_id == user_id)
            .order_by(ReviewAttempt.reviewed_at.desc(), ReviewAttempt.id.desc())
            .limit(RESPONSE_HISTORY_LIMIT)
        )
    )
    is_initial = len(rows) < MIN_HISTORY_FOR_ESTIMATE
    if is_initial:
        defaults = {
            "review": DEFAULT_REVIEW_SECONDS,
            "new": DEFAULT_NEW_SECONDS,
            "weak": DEFAULT_WEAK_SECONDS,
        }
        return defaults.get(kind, DEFAULT_REVIEW_SECONDS), True

    seconds = [max(1, int(ms // 1000) or 1) for ms in rows]
    median_seconds = max(15, min(600, _median(seconds)))
    if kind == "new":
        return min(600, max(30, int(median_seconds * 1.5))), False
    if kind == "weak":
        return min(600, max(20, int(median_seconds * 1.2))), False
    return median_seconds, False


def _subject_priority(profile: LearningProfile, subject: str | None) -> int:
    priorities = profile.subject_priorities or {}
    if subject and subject in priorities:
        return int(priorities[subject])
    return 0


def _load_profile(db: Session, user: User) -> LearningProfile:
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user.id).limit(1))
    if profile is None:
        raise DailyPlanStateError("learning profile is required before generating a plan")
    return profile


def _enrollments_for_cards(
    db: Session, *, user_id: int, card_ids: list[int]
) -> dict[int, CardEnrollment]:
    if not card_ids:
        return {}
    rows = db.scalars(
        select(CardEnrollment).where(
            CardEnrollment.user_id == user_id,
            CardEnrollment.card_id.in_(card_ids),
        )
    ).all()
    return {enrollment.card_id: enrollment for enrollment in rows}


def _card_subjects(db: Session, card_ids: list[int]) -> dict[int, str | None]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(Card.id, Book.subject)
        .join(Book, Book.id == Card.book_id)
        .where(Card.id.in_(card_ids))
    ).all()
    return {card_id: subject for card_id, subject in rows}


def _chapter_sorts_for_cards(db: Session, card_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(
            Card.id,
            func.min(Chapter.sort_order),
            func.min(DocumentChunk.pdf_page_index_start),
        )
        .select_from(Card)
        .outerjoin(CardSource, CardSource.card_id == Card.id)
        .outerjoin(DocumentChunk, DocumentChunk.id == CardSource.document_chunk_id)
        .outerjoin(Chapter, Chapter.id == DocumentChunk.chapter_id)
        .where(Card.id.in_(card_ids))
        .group_by(Card.id)
    ).all()
    return {
        card_id: (
            int(chapter_sort) if chapter_sort is not None else 10**9,
            int(page_start) if page_start is not None else 10**9,
        )
        for card_id, chapter_sort, page_start in rows
    }


def _build_due_candidates(
    db: Session,
    *,
    user_id: int,
    profile: LearningProfile,
    now: datetime,
    review_seconds: int,
    local_day: date,
    timezone_name: str,
) -> list[_Candidate]:
    due_states = list_due_review_states(db, user_id=user_id, now=now, limit=500)
    zone = _zoneinfo(timezone_name)
    due_card_ids = [state.card_id for state in due_states]
    enrollments = _enrollments_for_cards(db, user_id=user_id, card_ids=due_card_ids)
    subjects = _card_subjects(db, due_card_ids)
    candidates: list[_Candidate] = []
    for state in due_states:
        enrollment = enrollments.get(state.card_id)
        if enrollment is None or enrollment.status != EnrollmentStatus.ACTIVE.value:
            continue
        due_local = state.due_at.astimezone(zone).date()
        overdue_days = max(0, (local_day - due_local).days)
        is_overdue = overdue_days > 0
        subject = subjects.get(state.card_id)
        priority = _subject_priority(profile, subject)
        # Higher overdue first, higher subject priority first, earlier due first.
        sort_key = (
            0 if is_overdue else 1,
            -overdue_days,
            -priority,
            state.due_at.timestamp(),
            state.card_id,
            enrollment.id,
        )
        candidates.append(
            _Candidate(
                enrollment_id=enrollment.id,
                card_id=state.card_id,
                item_type="overdue" if is_overdue else "due",
                reason_code="OVERDUE" if is_overdue else "DUE",
                reason_detail=(
                    f"overdue_by_{overdue_days}d" if is_overdue else "due_today_or_earlier"
                ),
                estimated_seconds=review_seconds,
                sort_key=sort_key,
            )
        )
    candidates.sort(key=lambda item: item.sort_key)
    return candidates


def _build_weak_candidates(
    db: Session,
    *,
    user_id: int,
    profile: LearningProfile,
    now: datetime,
    weak_seconds: int,
    excluded_card_ids: set[int],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    suggestions = build_repair_suggestions(db, user_id=user_id, now=now, limit=500)
    weak_card_ids = [
        suggestion.card_id
        for suggestion in suggestions.items
        if suggestion.card_id not in excluded_card_ids
    ]
    enrollments = _enrollments_for_cards(db, user_id=user_id, card_ids=weak_card_ids)
    subjects = _card_subjects(db, weak_card_ids)
    for suggestion in suggestions.items:
        if suggestion.card_id in excluded_card_ids:
            continue
        enrollment = enrollments.get(suggestion.card_id)
        if enrollment is None or enrollment.status != EnrollmentStatus.ACTIVE.value:
            continue
        subject = subjects.get(suggestion.card_id)
        priority = _subject_priority(profile, subject)
        # Coach reason codes are namespaced REPAIR_* / WEAK_*; classify by prefix so
        # newly added weak-signal codes do not silently land as repair items.
        item_type = "repair" if suggestion.reason_code.startswith("REPAIR") else "weak_topic"
        candidates.append(
            _Candidate(
                enrollment_id=enrollment.id,
                card_id=suggestion.card_id,
                item_type=item_type,
                reason_code=suggestion.reason_code,
                reason_detail=suggestion.reason_detail,
                estimated_seconds=weak_seconds,
                sort_key=(
                    -priority,
                    -suggestion.severity_score,
                    suggestion.card_id,
                    enrollment.id,
                ),
            )
        )
    candidates.sort(key=lambda item: item.sort_key)
    return candidates


def _build_new_candidates(
    db: Session,
    *,
    user_id: int,
    profile: LearningProfile,
    new_seconds: int,
    excluded_card_ids: set[int],
    limit: int,
) -> list[_Candidate]:
    queued = list_queued_enrollments(db, user_id=user_id, limit=max(limit * 3, 20))
    queued_card_ids = [
        enrollment.card_id
        for enrollment in queued
        if enrollment.card_id not in excluded_card_ids
    ]
    subjects = _card_subjects(db, queued_card_ids)
    chapter_sorts = _chapter_sorts_for_cards(db, queued_card_ids)
    candidates: list[_Candidate] = []
    for index, enrollment in enumerate(queued):
        if enrollment.card_id in excluded_card_ids:
            continue
        subject = subjects.get(enrollment.card_id)
        priority = _subject_priority(profile, subject)
        chapter_sort, page_start = chapter_sorts.get(enrollment.card_id, (10**9, 10**9))
        reason = "NEW_FROM_PRIORITY_CHAPTER" if priority > 0 else "NEW_FROM_QUEUED"
        detail = f"subject_priority_{priority}" if priority > 0 else f"queue_order_{index}"
        candidates.append(
            _Candidate(
                enrollment_id=enrollment.id,
                card_id=enrollment.card_id,
                item_type="new",
                reason_code=reason,
                reason_detail=detail,
                estimated_seconds=new_seconds,
                sort_key=(
                    -enrollment.priority,
                    -priority,
                    chapter_sort,
                    page_start,
                    enrollment.card_id,
                    enrollment.id,
                ),
            )
        )
    candidates.sort(key=lambda item: item.sort_key)
    return candidates[:limit]


def _forecast_7d(
    db: Session,
    *,
    user_id: int,
    profile: LearningProfile,
    now: datetime,
    timezone_name: str,
    review_seconds: int,
) -> tuple[int, int]:
    zone = _zoneinfo(timezone_name)
    local_today = now.astimezone(zone).date()
    horizon = local_today + timedelta(days=6)
    horizon_end = datetime(
        horizon.year, horizon.month, horizon.day, 23, 59, 59, tzinfo=zone
    ).astimezone(UTC)

    due_count = (
        db.scalar(
            select(func.count())
            .select_from(CardReviewState)
            .join(
                CardEnrollment,
                and_(
                    CardEnrollment.user_id == CardReviewState.user_id,
                    CardEnrollment.card_id == CardReviewState.card_id,
                ),
            )
            .where(
                CardReviewState.user_id == user_id,
                CardReviewState.due_at <= horizon_end,
                CardEnrollment.status == EnrollmentStatus.ACTIVE.value,
            )
        )
        or 0
    )
    forecast_minutes = ceil((int(due_count) * review_seconds) / 60)

    budget = 0
    day = local_today
    study_days = list(profile.study_days or [True] * 7)
    for _ in range(7):
        if _is_study_day(study_days, day):
            budget += int(profile.daily_minutes)
        day += timedelta(days=1)
    return forecast_minutes, budget


def _is_weekly_mixed_day(study_days: list[bool], local_day: date) -> bool:
    # Insert mixed test on the last study day of the local week (Mon-Sun).
    last_study_offset = None
    for offset in range(7):
        if study_days[offset]:
            last_study_offset = offset
    if last_study_offset is None:
        return False
    return _weekday_index(local_day) == last_study_offset


def _build_mixed_candidates(
    db: Session,
    *,
    user_id: int,
    profile: LearningProfile,
    review_seconds: int,
    excluded_card_ids: set[int],
    now: datetime,
) -> list[_Candidate]:
    rows = list(
        db.execute(
            select(CardReviewState, CardEnrollment, Book.subject, Chapter.id)
            .select_from(CardReviewState)
            .join(
                CardEnrollment,
                and_(
                    CardEnrollment.user_id == CardReviewState.user_id,
                    CardEnrollment.card_id == CardReviewState.card_id,
                ),
            )
            .join(Card, Card.id == CardReviewState.card_id)
            .join(Book, Book.id == Card.book_id)
            .outerjoin(CardSource, CardSource.card_id == Card.id)
            .outerjoin(DocumentChunk, DocumentChunk.id == CardSource.document_chunk_id)
            .outerjoin(Chapter, Chapter.id == DocumentChunk.chapter_id)
            .where(
                CardReviewState.user_id == user_id,
                CardEnrollment.status == EnrollmentStatus.ACTIVE.value,
                CardReviewState.state.in_(("review", "relearning", "learning")),
                CardReviewState.reps >= 1,
                CardReviewState.due_at > now,
            )
            .order_by(CardReviewState.last_reviewed_at.desc().nullslast(), Card.id)
            .limit(100)
        ).all()
    )
    seen_chapters: set[int | None] = set()
    candidates: list[_Candidate] = []
    for state, enrollment, subject, chapter_id in rows:
        if state.card_id in excluded_card_ids:
            continue
        if chapter_id in seen_chapters and len(seen_chapters) < 2:
            # Prefer spreading across chapters; allow same chapter only after 2 unique.
            continue
        seen_chapters.add(chapter_id)
        priority = _subject_priority(profile, subject)
        candidates.append(
            _Candidate(
                enrollment_id=enrollment.id,
                card_id=state.card_id,
                item_type="mixed_weekly",
                reason_code="MIXED_WEEKLY",
                reason_detail="cross_chapter_weekly_check",
                estimated_seconds=review_seconds,
                sort_key=(-priority, state.card_id, enrollment.id),
            )
        )
        if len(candidates) >= MIXED_WEEKLY_LIMIT:
            break
    # Only keep if at least two chapters represented.
    if len(seen_chapters) < 2:
        return []
    return candidates


def _seconds_to_minutes(total_seconds: int) -> int:
    if total_seconds <= 0:
        return 0
    return max(1, ceil(total_seconds / 60))


def _fill_candidates(
    candidates: list[_Candidate],
    *,
    remaining_seconds: int,
    selected_card_ids: set[int],
    selected: list[_Candidate],
) -> int:
    for candidate in candidates:
        if candidate.card_id in selected_card_ids:
            continue
        if candidate.estimated_seconds > remaining_seconds:
            continue
        selected.append(candidate)
        selected_card_ids.add(candidate.card_id)
        remaining_seconds -= candidate.estimated_seconds
        if remaining_seconds <= 0:
            break
    return remaining_seconds


def _apply_counts(items: list[_Candidate | DailyPlanItem]) -> tuple[int, int, int, int]:
    due_count = sum(1 for item in items if item.item_type in {"due", "overdue"})
    new_count = sum(1 for item in items if item.item_type == "new")
    weak_count = sum(1 for item in items if item.item_type in {"weak_topic", "repair"})
    estimated_seconds = sum(item.estimated_seconds for item in items)
    return due_count, new_count, weak_count, estimated_seconds


def _get_existing_plan(db: Session, *, user_id: int, plan_date: str) -> DailyPlan | None:
    return db.scalar(
        select(DailyPlan)
        .options(joinedload(DailyPlan.items))
        .where(DailyPlan.user_id == user_id, DailyPlan.plan_date == plan_date)
        .limit(1)
    )


def _persist_plan(
    db: Session,
    *,
    user_id: int,
    plan_date: str,
    budget_minutes: int,
    adjusted_budget_minutes: int | None,
    items: list[_Candidate],
    is_initial: bool,
    forecast_minutes_7d: int,
    forecast_budget_7d: int,
    new_cards_paused: bool,
    pause_reasons: list[str],
    plan_reasons: list[str],
    now: datetime,
    existing: DailyPlan | None = None,
    historical_items: list[DailyPlanItem] | None = None,
) -> DailyPlan:
    history = sorted(historical_items or [], key=lambda row: row.position)
    all_items: list[_Candidate | DailyPlanItem] = [*history, *items]
    due_count, new_count, weak_count, estimated_seconds = _apply_counts(all_items)
    estimated_minutes = _seconds_to_minutes(estimated_seconds) if all_items else 0
    timestamp = _require_aware_utc(now)

    if existing is None:
        plan = DailyPlan(
            user_id=user_id,
            plan_date=plan_date,
            budget_minutes=budget_minutes,
            adjusted_budget_minutes=adjusted_budget_minutes,
            estimated_minutes=estimated_minutes,
            due_count=due_count,
            new_count=new_count,
            weak_count=weak_count,
            generation_version=GENERATION_VERSION,
            is_initial=is_initial,
            forecast_minutes_7d=forecast_minutes_7d,
            forecast_budget_7d=forecast_budget_7d,
            new_cards_paused=new_cards_paused,
            pause_reasons=list(pause_reasons),
            plan_reasons=list(plan_reasons),
            generated_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(plan)
        db.flush()
    else:
        plan = existing
        plan.budget_minutes = budget_minutes
        plan.adjusted_budget_minutes = adjusted_budget_minutes
        plan.estimated_minutes = estimated_minutes
        plan.due_count = due_count
        plan.new_count = new_count
        plan.weak_count = weak_count
        plan.generation_version = GENERATION_VERSION
        plan.is_initial = is_initial
        plan.forecast_minutes_7d = forecast_minutes_7d
        plan.forecast_budget_7d = forecast_budget_7d
        plan.new_cards_paused = new_cards_paused
        plan.pause_reasons = list(pause_reasons)
        plan.plan_reasons = list(plan_reasons)
        plan.generated_at = timestamp
        plan.updated_at = timestamp
        historical_ids = {item.id for item in history}
        for stored_item in list(plan.items):
            if stored_item.id not in historical_ids:
                db.delete(stored_item)
        db.flush()

    first_pending_position = max((item.position for item in history), default=-1) + 1
    for position, candidate in enumerate(items, start=first_pending_position):
        db.add(
            DailyPlanItem(
                plan_id=plan.id,
                position=position,
                item_type=candidate.item_type,
                enrollment_id=candidate.enrollment_id,
                card_id=candidate.card_id,
                estimated_seconds=candidate.estimated_seconds,
                reason_code=candidate.reason_code,
                reason_detail=candidate.reason_detail,
                status="pending",
                created_at=timestamp,
            )
        )
    study_session = db.scalar(
        select(StudySession).where(StudySession.daily_plan_id == plan.id).limit(1)
    )
    if study_session is not None and study_session.status not in {"completed", "cancelled"}:
        study_session.planned_task_count = study_session.completed_task_count + len(items)
        study_session.estimated_minutes = estimated_minutes
        study_session.cursor_position = first_pending_position
        study_session.updated_at = timestamp
    db.commit()
    db.refresh(plan)
    reloaded = db.scalar(
        select(DailyPlan)
        .options(joinedload(DailyPlan.items))
        .where(DailyPlan.id == plan.id)
        .limit(1)
    )
    if reloaded is None:
        raise DailyPlanStateError("daily plan disappeared after persistence")
    return reloaded


def generate_daily_plan(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
    budget_override: int | None = None,
    preserve_pending: list[DailyPlanItem] | None = None,
    preserve_history: list[DailyPlanItem] | None = None,
    existing: DailyPlan | None = None,
) -> DailyPlan:
    """Generate a deterministic DailyPlan for the user's local date."""
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise DailyPlanReferenceError("an active Owner is required")
    profile = _load_profile(db, user)
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    local_day = _local_date(timestamp, user.timezone)
    plan_date = local_day.isoformat()
    study_days = list(profile.study_days or [True] * 7)

    base_budget = int(profile.daily_minutes)
    adjusted = budget_override
    if adjusted is not None and not (5 <= adjusted <= 240):
        raise DailyPlanStateError("budget minutes must be between 5 and 240")
    effective_budget = int(adjusted if adjusted is not None else base_budget)
    budget_seconds = effective_budget * 60

    review_seconds, review_default = _estimate_seconds(db, user_id=user_id, kind="review")
    new_seconds, new_default = _estimate_seconds(db, user_id=user_id, kind="new")
    weak_seconds, weak_default = _estimate_seconds(db, user_id=user_id, kind="weak")
    is_initial = review_default and new_default and weak_default

    forecast_minutes_7d, forecast_budget_7d = _forecast_7d(
        db,
        user_id=user_id,
        profile=profile,
        now=timestamp,
        timezone_name=user.timezone,
        review_seconds=review_seconds,
    )

    pause_reasons: list[str] = []
    plan_reasons: list[str] = []
    if is_initial:
        plan_reasons.append("INITIAL_CONSERVATIVE_DEFAULTS")
    if not _is_study_day(study_days, local_day):
        plan_reasons.append("NON_STUDY_DAY_DUE_ONLY")

    due_candidates = _build_due_candidates(
        db,
        user_id=user_id,
        profile=profile,
        now=timestamp,
        review_seconds=review_seconds,
        local_day=local_day,
        timezone_name=user.timezone,
    )
    due_seconds = sum(item.estimated_seconds for item in due_candidates)
    backlog = due_seconds > budget_seconds
    if backlog:
        pause_reasons.append("BACKLOG_EXCEEDS_BUDGET")
        plan_reasons.append("DUE_PRIORITY_BACKLOG")
    if forecast_minutes_7d > forecast_budget_7d:
        pause_reasons.append("FORECAST_7D_OVER_BUDGET")

    new_cards_paused = bool(pause_reasons) or effective_budget <= 0

    selected: list[_Candidate] = []
    history = sorted(preserve_history or [], key=lambda row: row.position)
    selected_card_ids: set[int] = {item.card_id for item in history}
    completed_seconds = sum(
        item.estimated_seconds for item in history if item.status == "completed"
    )
    remaining = max(0, budget_seconds - completed_seconds)
    if completed_seconds > budget_seconds:
        plan_reasons.append("BUDGET_REDUCED_AFTER_COMPLETION")
    due_candidates = [
        candidate for candidate in due_candidates if candidate.card_id not in selected_card_ids
    ]

    # PLAN-006: never drop unfinished items when adjusting budget.
    if preserve_pending:
        for item in sorted(preserve_pending, key=lambda row: row.position):
            if item.status != "pending":
                continue
            if item.card_id in selected_card_ids:
                continue
            candidate = _Candidate(
                enrollment_id=item.enrollment_id,
                card_id=item.card_id,
                item_type=item.item_type,
                reason_code=item.reason_code,
                reason_detail=item.reason_detail,
                estimated_seconds=item.estimated_seconds,
                sort_key=(item.position,),
            )
            selected.append(candidate)
            selected_card_ids.add(item.card_id)
            remaining -= item.estimated_seconds
        if remaining < 0:
            plan_reasons.append("BUDGET_REDUCED_KEEP_PENDING")
            remaining = 0

    # Always try to place at least one due item when plan empty and due exists,
    # even if it slightly exceeds a tiny budget.
    if not selected and due_candidates and (remaining > 0 or not history):
        first = due_candidates[0]
        selected.append(first)
        selected_card_ids.add(first.card_id)
        remaining = max(0, remaining - first.estimated_seconds)
        due_candidates = due_candidates[1:]

    remaining = _fill_candidates(
        due_candidates,
        remaining_seconds=remaining,
        selected_card_ids=selected_card_ids,
        selected=selected,
    )

    # Weak/repair only after dues, and only on study days with remaining budget.
    if remaining > 0 and _is_study_day(study_days, local_day):
        weak_candidates = _build_weak_candidates(
            db,
            user_id=user_id,
            profile=profile,
            now=timestamp,
            weak_seconds=weak_seconds,
            excluded_card_ids=selected_card_ids,
        )
        remaining = _fill_candidates(
            weak_candidates,
            remaining_seconds=remaining,
            selected_card_ids=selected_card_ids,
            selected=selected,
        )

    # New cards after due+weak when not paused.
    if remaining > 0 and not new_cards_paused and _is_study_day(study_days, local_day):
        ceiling = max(0, int(profile.new_card_ceiling))
        new_candidates = _build_new_candidates(
            db,
            user_id=user_id,
            profile=profile,
            new_seconds=new_seconds,
            excluded_card_ids=selected_card_ids,
            limit=ceiling,
        )
        remaining = _fill_candidates(
            new_candidates,
            remaining_seconds=remaining,
            selected_card_ids=selected_card_ids,
            selected=selected,
        )
        if any(item.item_type == "new" for item in selected):
            plan_reasons.append("NEW_AFTER_DUE")
    elif new_cards_paused:
        plan_reasons.append("NEW_CARDS_PAUSED")

    # Weekly mixed test last, low priority.
    if (
        remaining > 0
        and _is_study_day(study_days, local_day)
        and _is_weekly_mixed_day(study_days, local_day)
    ):
        mixed = _build_mixed_candidates(
            db,
            user_id=user_id,
            profile=profile,
            review_seconds=review_seconds,
            excluded_card_ids=selected_card_ids,
            now=timestamp,
        )
        remaining = _fill_candidates(
            mixed,
            remaining_seconds=remaining,
            selected_card_ids=selected_card_ids,
            selected=selected,
        )
        if any(item.item_type == "mixed_weekly" for item in selected):
            plan_reasons.append("MIXED_WEEKLY_INSERTED")

    if any(item.reason_code == "DUE" for item in selected):
        plan_reasons.append("DUE_FIRST")
    if any(item.reason_code == "OVERDUE" for item in selected):
        plan_reasons.append("OVERDUE_FIRST")
    if any(item.item_type in {"weak_topic", "repair"} for item in selected):
        plan_reasons.append("WEAK_OR_REPAIR_INCLUDED")

    # Stable unique plan_reasons order
    seen: set[str] = set()
    ordered_reasons: list[str] = []
    for reason in plan_reasons:
        if reason not in seen:
            seen.add(reason)
            ordered_reasons.append(reason)

    return _persist_plan(
        db,
        user_id=user_id,
        plan_date=plan_date,
        budget_minutes=base_budget,
        adjusted_budget_minutes=adjusted,
        items=selected,
        is_initial=is_initial,
        forecast_minutes_7d=forecast_minutes_7d,
        forecast_budget_7d=forecast_budget_7d,
        new_cards_paused=new_cards_paused,
        pause_reasons=sorted(set(pause_reasons)),
        plan_reasons=ordered_reasons,
        now=timestamp,
        existing=existing,
        historical_items=history,
    )


def get_or_create_today_plan(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
    regenerate: bool = False,
) -> DailyPlan:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise DailyPlanReferenceError("an active Owner is required")
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    plan_date = _local_date(timestamp, user.timezone).isoformat()
    existing = _get_existing_plan(db, user_id=user_id, plan_date=plan_date)
    if existing is not None and not regenerate:
        return existing
    try:
        return generate_daily_plan(
            db,
            user_id=user_id,
            now=timestamp,
            budget_override=existing.adjusted_budget_minutes if existing else None,
            existing=existing if regenerate else None,
        )
    except IntegrityError:
        # A concurrent request created today's plan first; return the winner's plan.
        db.rollback()
        existing = _get_existing_plan(db, user_id=user_id, plan_date=plan_date)
        if existing is not None:
            return existing
        raise


def adjust_today_budget(
    db: Session,
    *,
    user_id: int,
    budget_minutes: int,
    now: datetime | None = None,
) -> DailyPlan:
    """Temporarily adjust today's budget without dropping unfinished items."""
    if not (5 <= budget_minutes <= 240):
        raise DailyPlanStateError("budget minutes must be between 5 and 240")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise DailyPlanReferenceError("an active Owner is required")
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    plan = get_or_create_today_plan(db, user_id=user_id, now=timestamp)
    pending = [item for item in plan.items if item.status == "pending"]
    history = [item for item in plan.items if item.status != "pending"]
    return generate_daily_plan(
        db,
        user_id=user_id,
        now=timestamp,
        budget_override=budget_minutes,
        preserve_pending=pending,
        preserve_history=history,
        existing=plan,
    )
