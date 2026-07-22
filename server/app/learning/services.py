from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog.models import Card
from ..identity.models import User
from .models import CardEnrollment, CardReviewState
from .schemas import EnrollmentCreate, EnrollmentStatus


class EnrollmentReferenceError(RuntimeError):
    pass


class EnrollmentStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnrollmentResult:
    enrollment: CardEnrollment
    created: bool


@dataclass(frozen=True)
class IntroductionResult:
    enrollment: CardEnrollment
    review_state: CardReviewState
    state_created: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a timezone")
    return value.astimezone(UTC)


def _eligible_user_and_card(db: Session, *, user_id: int, card_id: int) -> tuple[User, Card]:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise EnrollmentReferenceError("an active Owner is required")
    card = db.get(Card, card_id)
    if card is None or card.status not in {"approved", "published"}:
        raise EnrollmentReferenceError("only approved or published cards can be enrolled")
    return user, card


def enroll_card(
    db: Session, values: EnrollmentCreate, *, now: datetime | None = None
) -> EnrollmentResult:
    _eligible_user_and_card(db, user_id=values.user_id, card_id=values.card_id)
    timestamp = _require_aware_utc(now or _utc_now())
    existing = db.scalar(
        select(CardEnrollment)
        .where(
            CardEnrollment.user_id == values.user_id,
            CardEnrollment.card_id == values.card_id,
        )
        .limit(1)
    )
    if existing is not None:
        return EnrollmentResult(enrollment=existing, created=False)

    enrollment = CardEnrollment(
        user_id=values.user_id,
        card_id=values.card_id,
        status=EnrollmentStatus.QUEUED.value,
        priority=values.priority,
        source=values.source.value,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CardEnrollment)
            .where(
                CardEnrollment.user_id == values.user_id,
                CardEnrollment.card_id == values.card_id,
            )
            .limit(1)
        )
        if existing is not None:
            return EnrollmentResult(enrollment=existing, created=False)
        raise EnrollmentStateError("enrollment conflicts with existing data") from exc
    db.refresh(enrollment)
    return EnrollmentResult(enrollment=enrollment, created=True)


def introduce_enrollment(
    db: Session,
    *,
    enrollment_id: int,
    algorithm_version: str = "fsrs-v1",
    now: datetime | None = None,
) -> IntroductionResult:
    enrollment = db.get(CardEnrollment, enrollment_id)
    if enrollment is None:
        raise EnrollmentReferenceError("enrollment does not exist")
    if enrollment.status in {EnrollmentStatus.SUSPENDED.value, EnrollmentStatus.RETIRED.value}:
        raise EnrollmentStateError("suspended or retired enrollment cannot be introduced")
    _eligible_user_and_card(db, user_id=enrollment.user_id, card_id=enrollment.card_id)
    algorithm_version = algorithm_version.strip()
    if not algorithm_version or len(algorithm_version) > 32:
        raise EnrollmentStateError("algorithm_version must contain 1 to 32 characters")
    timestamp = _require_aware_utc(now or _utc_now())
    state = db.scalar(
        select(CardReviewState)
        .where(
            CardReviewState.user_id == enrollment.user_id,
            CardReviewState.card_id == enrollment.card_id,
        )
        .limit(1)
    )
    state_created = state is None
    if state is None:
        state = CardReviewState(
            user_id=enrollment.user_id,
            card_id=enrollment.card_id,
            due_at=timestamp,
            stability=1.0,
            difficulty=5.0,
            elapsed_days=0.0,
            scheduled_days=0.0,
            reps=0,
            lapses=0,
            state="new",
            algorithm_version=algorithm_version,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(state)

    enrollment.status = EnrollmentStatus.ACTIVE.value
    if enrollment.introduced_at is None:
        enrollment.introduced_at = timestamp
    enrollment.updated_at = timestamp
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        enrollment = db.get(CardEnrollment, enrollment_id)
        if enrollment is None:
            raise EnrollmentStateError("enrollment disappeared during introduction") from exc
        state = db.scalar(
            select(CardReviewState)
            .where(
                CardReviewState.user_id == enrollment.user_id,
                CardReviewState.card_id == enrollment.card_id,
            )
            .limit(1)
        )
        if state is None:
            raise EnrollmentStateError("review state conflicts with existing data") from exc
        return IntroductionResult(enrollment=enrollment, review_state=state, state_created=False)
    db.refresh(enrollment)
    db.refresh(state)
    return IntroductionResult(
        enrollment=enrollment,
        review_state=state,
        state_created=state_created,
    )


def change_enrollment_status(
    db: Session,
    *,
    enrollment_id: int,
    target_status: EnrollmentStatus,
    now: datetime | None = None,
) -> CardEnrollment:
    enrollment = db.get(CardEnrollment, enrollment_id)
    if enrollment is None:
        raise EnrollmentReferenceError("enrollment does not exist")
    if enrollment.status == target_status.value:
        return enrollment
    if target_status == EnrollmentStatus.QUEUED:
        raise EnrollmentStateError("queued is only entered through enroll_card")
    if target_status == EnrollmentStatus.SUSPENDED and enrollment.status != EnrollmentStatus.ACTIVE:
        raise EnrollmentStateError("only an active enrollment can be suspended")
    if target_status == EnrollmentStatus.ACTIVE:
        if enrollment.status != EnrollmentStatus.SUSPENDED.value:
            raise EnrollmentStateError("only a suspended enrollment can be resumed")
        state_id = db.scalar(
            select(CardReviewState.id).where(
                CardReviewState.user_id == enrollment.user_id,
                CardReviewState.card_id == enrollment.card_id,
            )
        )
        if state_id is None:
            raise EnrollmentStateError("introduce the enrollment before activating it")
    if target_status == EnrollmentStatus.RETIRED and enrollment.status not in {
        EnrollmentStatus.QUEUED.value,
        EnrollmentStatus.ACTIVE.value,
        EnrollmentStatus.SUSPENDED.value,
    }:
        raise EnrollmentStateError("enrollment cannot transition to retired")
    enrollment.status = target_status.value
    enrollment.updated_at = _require_aware_utc(now or _utc_now())
    db.commit()
    db.refresh(enrollment)
    return enrollment


def list_due_review_states(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
    limit: int = 100,
) -> list[CardReviewState]:
    timestamp = _require_aware_utc(now or _utc_now())
    return list(
        db.scalars(
            select(CardReviewState)
            .join(
                CardEnrollment,
                and_(
                    CardEnrollment.user_id == CardReviewState.user_id,
                    CardEnrollment.card_id == CardReviewState.card_id,
                ),
            )
            .join(Card, Card.id == CardReviewState.card_id)
            .join(User, User.id == CardReviewState.user_id)
            .where(
                CardReviewState.user_id == user_id,
                CardReviewState.due_at <= timestamp,
                CardEnrollment.status == EnrollmentStatus.ACTIVE.value,
                Card.status.in_(("approved", "published")),
                User.status == "active",
            )
            .order_by(CardReviewState.due_at, CardReviewState.id)
            .limit(min(max(limit, 1), 500))
        )
    )
