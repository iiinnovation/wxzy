from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catalog.models import Book, Card, DocumentChunk, DocumentVersion
from ..identity.models import LearningProfile, User
from .coach import build_repair_suggestions
from .daily_plan import _estimate_seconds, _is_study_day
from .models import CardEnrollment, CardReviewState, ReviewAttempt, StudySession
from .schemas import (
    InsightContentProgressOut,
    InsightSubjectTrendOut,
    InsightSummaryOut,
    InsightWeakTopicPageOut,
    InsightWorkloadDayOut,
    InsightWorkloadOut,
)
from .services import _require_aware_utc, is_mastered_state

UNCATEGORIZED_SUBJECT = "未分类"


class InsightReferenceError(RuntimeError):
    pass


class InsightStateError(RuntimeError):
    pass


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise InsightStateError(f"invalid owner timezone: {name}") from exc


def _owner(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise InsightReferenceError("an active Owner is required")
    return user


def _local_bounds(local_day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(local_day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


def _is_new_attempt(attempt: Any) -> bool:
    """Accepts any row exposing state_before (ORM entity or column projection)."""
    return str((attempt.state_before or {}).get("state", "")) == "new"


def _mastered_card_ids(states: list[CardReviewState], *, now: datetime) -> set[int]:
    return {state.card_id for state in states if is_mastered_state(state, now=now)}


def _content_progress(
    db: Session, *, user_id: int, mastered_ids: set[int]
) -> InsightContentProgressOut:
    versions = list(
        db.scalars(
            select(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.id.desc())
        )
    )
    latest_by_document: dict[int, DocumentVersion] = {}
    for version in versions:
        latest_by_document.setdefault(version.document_id, version)
    latest_versions = list(latest_by_document.values())
    page_count = sum(version.page_count for version in latest_versions)
    covered = 0
    for version in latest_versions:
        pages: set[int] = set()
        chunks = db.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_version_id == version.id,
                DocumentChunk.quality_status.in_(("ready", "needs_review", "failed")),
            )
        )
        for chunk in chunks:
            pages.update(
                range(
                    max(0, chunk.pdf_page_index_start),
                    min(version.page_count - 1, chunk.pdf_page_index_end) + 1,
                )
            )
        covered += len(pages)

    published = len(set(db.scalars(select(Card.id).where(Card.status == "published"))))
    enrollments = list(
        db.scalars(
            select(CardEnrollment).where(
                CardEnrollment.user_id == user_id,
                CardEnrollment.status != "retired",
            )
        )
    )
    active_count = sum(row.status == "active" for row in enrollments)
    return InsightContentProgressOut(
        document_page_count=page_count,
        covered_page_count=covered,
        coverage_ratio=(covered / page_count if page_count else 0.0),
        published_card_count=published,
        enrolled_card_count=len(enrollments),
        active_card_count=active_count,
        mastered_card_count=len(mastered_ids),
    )


def _subject_trends(
    db: Session, *, user_id: int, now: datetime, mastered_ids: set[int]
) -> list[InsightSubjectTrendOut]:
    cards = db.execute(
        select(Card.id, Card.status, Book.subject).join(Book, Book.id == Card.book_id)
    ).all()
    subject_by_card = {
        card_id: (subject or UNCATEGORIZED_SUBJECT) for card_id, _status, subject in cards
    }
    published_by_subject: dict[str, set[int]] = defaultdict(set)
    for card_id, status, subject in cards:
        if status == "published":
            published_by_subject[subject or UNCATEGORIZED_SUBJECT].add(card_id)

    enrolled_by_subject: dict[str, set[int]] = defaultdict(set)
    active_by_subject: dict[str, set[int]] = defaultdict(set)
    for enrollment in db.scalars(
        select(CardEnrollment).where(
            CardEnrollment.user_id == user_id,
            CardEnrollment.status != "retired",
        )
    ):
        subject = subject_by_card.get(enrollment.card_id, UNCATEGORIZED_SUBJECT)
        enrolled_by_subject[subject].add(enrollment.card_id)
        if enrollment.status == "active":
            active_by_subject[subject].add(enrollment.card_id)

    attempts = list(
        db.scalars(
            select(ReviewAttempt).where(
                ReviewAttempt.user_id == user_id,
                ReviewAttempt.reviewed_at >= now - timedelta(days=30),
            )
        )
    )
    attempts_by_subject: dict[str, list[ReviewAttempt]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_subject[subject_by_card.get(attempt.card_id, UNCATEGORIZED_SUBJECT)].append(
            attempt
        )

    subjects = sorted(
        set(published_by_subject) | set(enrolled_by_subject) | set(attempts_by_subject)
    )
    result: list[InsightSubjectTrendOut] = []
    split = now - timedelta(days=15)
    for subject in subjects:
        rows = attempts_by_subject[subject]
        recent = [row for row in rows if row.reviewed_at >= split]
        previous = [row for row in rows if row.reviewed_at < split]
        success_rate = sum(row.rating >= 3 for row in rows) / len(rows) if rows else None
        trend = "insufficient"
        if len(recent) >= 2 and len(previous) >= 2:
            recent_rate = sum(row.rating >= 3 for row in recent) / len(recent)
            previous_rate = sum(row.rating >= 3 for row in previous) / len(previous)
            delta = recent_rate - previous_rate
            trend = "improving" if delta >= 0.15 else "declining" if delta <= -0.15 else "stable"
        result.append(
            InsightSubjectTrendOut(
                subject=subject,
                published_card_count=len(published_by_subject[subject]),
                enrolled_card_count=len(enrolled_by_subject[subject]),
                active_card_count=len(active_by_subject[subject]),
                mastered_card_count=len(mastered_ids & active_by_subject[subject]),
                attempt_count_30d=len(rows),
                again_count_30d=sum(row.rating == 1 for row in rows),
                hard_count_30d=sum(row.rating == 2 for row in rows),
                success_rate_30d=success_rate,
                trend=trend,
            )
        )
    return result


def build_insight_summary(
    db: Session, *, user_id: int, now: datetime | None = None
) -> InsightSummaryOut:
    user = _owner(db, user_id)
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    zone = _zone(user.timezone)
    local_day = timestamp.astimezone(zone).date()
    day_start, day_end = _local_bounds(local_day, zone)
    # The attempt history is unbounded; project only the two columns the counts need.
    attempts = db.execute(
        select(ReviewAttempt.reviewed_at, ReviewAttempt.state_before).where(
            ReviewAttempt.user_id == user_id
        )
    ).all()
    sessions = list(
        db.scalars(
            select(StudySession).where(
                StudySession.user_id == user_id,
                StudySession.status.in_(("completed", "interrupted")),
            )
        )
    )
    today_attempts = [row for row in attempts if day_start <= row.reviewed_at < day_end]
    today_sessions = [
        row for row in sessions if row.ended_at is not None and day_start <= row.ended_at < day_end
    ]
    study_dates = {row.reviewed_at.astimezone(zone).date() for row in attempts} | {
        row.ended_at.astimezone(zone).date()
        for row in sessions
        if row.ended_at is not None and row.actual_minutes > 0
    }
    active_states = list(
        db.scalars(
            select(CardReviewState)
            .join(
                CardEnrollment,
                (CardEnrollment.user_id == CardReviewState.user_id)
                & (CardEnrollment.card_id == CardReviewState.card_id),
            )
            .where(
                CardReviewState.user_id == user_id,
                CardEnrollment.status == "active",
            )
        )
    )
    mastered_ids = _mastered_card_ids(active_states, now=timestamp)
    return InsightSummaryOut(
        user_id=user_id,
        timezone=user.timezone,
        local_date=local_day.isoformat(),
        generated_at=timestamp,
        study_days=len(study_dates),
        total_actual_minutes=sum(row.actual_minutes for row in sessions),
        total_review_count=len(attempts),
        total_new_count=sum(_is_new_attempt(row) for row in attempts),
        today_actual_minutes=sum(row.actual_minutes for row in today_sessions),
        today_review_count=len(today_attempts),
        today_new_count=sum(_is_new_attempt(row) for row in today_attempts),
        current_due_count=sum(row.due_at <= timestamp for row in active_states),
        backlog_count=sum(row.due_at < day_start for row in active_states),
        content=_content_progress(db, user_id=user_id, mastered_ids=mastered_ids),
        subjects=_subject_trends(db, user_id=user_id, now=timestamp, mastered_ids=mastered_ids),
    )


def build_insight_workload(
    db: Session, *, user_id: int, now: datetime | None = None
) -> InsightWorkloadOut:
    user = _owner(db, user_id)
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    zone = _zone(user.timezone)
    local_today = timestamp.astimezone(zone).date()
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user_id).limit(1))
    daily_minutes = int(profile.daily_minutes) if profile else 20
    study_days = list(profile.study_days or [True] * 7) if profile else [True] * 7
    seconds, _ = _estimate_seconds(db, user_id=user_id, kind="review")
    states = list(
        db.scalars(
            select(CardReviewState)
            .join(
                CardEnrollment,
                (CardEnrollment.user_id == CardReviewState.user_id)
                & (CardEnrollment.card_id == CardReviewState.card_id),
            )
            .where(
                CardReviewState.user_id == user_id,
                CardEnrollment.status == "active",
            )
        )
    )
    counts = {local_today + timedelta(days=offset): 0 for offset in range(7)}
    overdue = 0
    horizon = local_today + timedelta(days=6)
    for state in states:
        due_day = state.due_at.astimezone(zone).date()
        if due_day < local_today:
            counts[local_today] += 1
            overdue += 1
        elif due_day <= horizon:
            counts[due_day] += 1
    days: list[InsightWorkloadDayOut] = []
    for local_day, due_count in counts.items():
        budget = daily_minutes if _is_study_day(study_days, local_day) else 0
        estimated = ceil((due_count * seconds) / 60) if due_count else 0
        days.append(
            InsightWorkloadDayOut(
                local_date=local_day.isoformat(),
                due_count=due_count,
                overdue_count=overdue if local_day == local_today else 0,
                estimated_minutes=estimated,
                budget_minutes=budget,
                overloaded=estimated > budget,
            )
        )
    total_estimated = sum(day.estimated_minutes for day in days)
    total_budget = sum(day.budget_minutes for day in days)
    return InsightWorkloadOut(
        user_id=user_id,
        timezone=user.timezone,
        generated_at=timestamp,
        review_seconds_estimate=seconds,
        total_due_count=sum(day.due_count for day in days),
        total_estimated_minutes=total_estimated,
        total_budget_minutes=total_budget,
        overloaded=total_estimated > total_budget or any(day.overloaded for day in days),
        days=days,
    )


def build_weak_topic_page(
    db: Session,
    *,
    user_id: int,
    offset: int = 0,
    limit: int = 20,
    now: datetime | None = None,
) -> InsightWeakTopicPageOut:
    _owner(db, user_id)
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    if offset < 0 or not 1 <= limit <= 100:
        raise InsightStateError("offset/limit is outside the supported range")
    suggestions = build_repair_suggestions(
        db,
        user_id=user_id,
        now=timestamp,
        limit=10_000,
    )
    total = len(suggestions.items)
    return InsightWeakTopicPageOut(
        user_id=user_id,
        generated_at=timestamp,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
        items=suggestions.items[offset : offset + limit],
    )
