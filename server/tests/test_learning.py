from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import Book, Card
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.learning.models import CardEnrollment, CardReviewState
from app.learning.schemas import EnrollmentCreate, EnrollmentSource, EnrollmentStatus
from app.learning.services import (
    EnrollmentReferenceError,
    EnrollmentStateError,
    change_enrollment_status,
    enroll_card,
    introduce_enrollment,
    list_due_review_states,
)


def _clean_learning_rows(db: Session) -> None:
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("learning-test-%")))
    db.execute(delete(Book).where(Book.name.like("Learning Test%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean_learning_rows(session)
        yield session
        session.rollback()
        _clean_learning_rows(session)


def _create_owner(db: Session) -> User:
    return create_owner_with_default_profile(
        db,
        OwnerCreate(display_name="Learning Test Owner", timezone="Asia/Shanghai"),
        now=datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
    )


def _publish_cards(db: Session, *, count: int, status: str = "published") -> list[Card]:
    book = Book(name=f"Learning Test Book {count}-{status}", subject="测试")
    db.add(book)
    db.flush()
    cards = [
        Card(
            external_id=f"learning-test-{status}-{count}-{index}",
            book_id=book.id,
            card_type="definition",
            question=f"问题 {index}",
            answer=f"答案 {index}",
            source_excerpt="来源摘录",
            status=status,
            content_revision=1,
            content_hash=f"{index:064x}"[-64:],
            answer_points=[],
            tags=[],
        )
        for index in range(count)
    ]
    db.add_all(cards)
    db.commit()
    return cards


def test_published_cards_stay_out_of_due_until_planned_introduction(db: Session) -> None:
    owner = _create_owner(db)
    cards = _publish_cards(db, count=100)
    introduced_at = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)

    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 0
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 0
    assert list_due_review_states(db, user_id=owner.id, now=introduced_at) == []

    enrollments = [
        enroll_card(
            db,
            EnrollmentCreate(
                user_id=owner.id,
                card_id=card.id,
                priority=80 - index,
                source=EnrollmentSource.PLAN,
            ),
            now=introduced_at - timedelta(minutes=5),
        ).enrollment
        for index, card in enumerate(cards[:5])
    ]

    assert {enrollment.status for enrollment in enrollments} == {"queued"}
    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 5
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 0
    assert list_due_review_states(db, user_id=owner.id, now=introduced_at) == []

    duplicate = enroll_card(
        db,
        EnrollmentCreate(user_id=owner.id, card_id=cards[0].id, source=EnrollmentSource.PLAN),
        now=introduced_at,
    )
    assert duplicate.created is False
    assert duplicate.enrollment.id == enrollments[0].id
    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 5

    introductions = [
        introduce_enrollment(db, enrollment_id=enrollment.id, now=introduced_at)
        for enrollment in enrollments
    ]
    due_states = list_due_review_states(db, user_id=owner.id, now=introduced_at)

    assert all(result.state_created for result in introductions)
    assert {state.card_id for state in due_states} == {card.id for card in cards[:5]}
    assert len(due_states) == 5
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 5
    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 5
    assert all(state.user_id == owner.id for state in due_states)
    assert all(
        state.state == "new" and state.reps == 0 and state.lapses == 0 for state in due_states
    )
    assert all(state.due_at == introduced_at and state.due_at.tzinfo is UTC for state in due_states)

    repeated = introduce_enrollment(db, enrollment_id=enrollments[0].id, now=introduced_at)
    assert repeated.state_created is False
    assert repeated.review_state.id == introductions[0].review_state.id
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 5


def test_database_enforces_one_enrollment_and_state_per_user_card(db: Session) -> None:
    owner = _create_owner(db)
    card = _publish_cards(db, count=1)[0]
    enrollment = enroll_card(
        db, EnrollmentCreate(user_id=owner.id, card_id=card.id), now=datetime.now(UTC)
    ).enrollment

    db.add(
        CardEnrollment(
            user_id=owner.id,
            card_id=card.id,
            status="queued",
            priority=50,
            source="manual",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    introduction = introduce_enrollment(db, enrollment_id=enrollment.id, now=datetime.now(UTC))
    db.add(
        CardReviewState(
            user_id=owner.id,
            card_id=card.id,
            due_at=datetime.now(UTC),
            algorithm_version="fsrs-v1",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 1
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 1
    assert db.get(CardReviewState, introduction.review_state.id) is not None


def test_suspend_resume_and_retire_preserve_review_state(db: Session) -> None:
    owner = _create_owner(db)
    card = _publish_cards(db, count=1)[0]
    now = datetime(2026, 7, 22, 5, 0, tzinfo=UTC)
    enrollment = enroll_card(
        db, EnrollmentCreate(user_id=owner.id, card_id=card.id), now=now
    ).enrollment
    introduction = introduce_enrollment(db, enrollment_id=enrollment.id, now=now)
    state_id = introduction.review_state.id
    first_introduced_at = introduction.enrollment.introduced_at

    change_enrollment_status(
        db,
        enrollment_id=enrollment.id,
        target_status=EnrollmentStatus.SUSPENDED,
        now=now + timedelta(minutes=1),
    )
    assert list_due_review_states(db, user_id=owner.id, now=now) == []
    assert db.get(CardReviewState, state_id) is not None

    change_enrollment_status(
        db,
        enrollment_id=enrollment.id,
        target_status=EnrollmentStatus.ACTIVE,
        now=now + timedelta(minutes=2),
    )
    assert [state.id for state in list_due_review_states(db, user_id=owner.id, now=now)] == [
        state_id
    ]

    change_enrollment_status(
        db,
        enrollment_id=enrollment.id,
        target_status=EnrollmentStatus.RETIRED,
        now=now + timedelta(minutes=3),
    )
    assert list_due_review_states(db, user_id=owner.id, now=now) == []
    assert db.get(CardReviewState, state_id) is not None

    reenrolled = enroll_card(
        db,
        EnrollmentCreate(
            user_id=owner.id,
            card_id=card.id,
            priority=90,
            source=EnrollmentSource.CHAPTER,
        ),
        now=now + timedelta(minutes=4),
    )
    assert reenrolled.created is False
    assert reenrolled.enrollment.status == "retired"
    assert reenrolled.enrollment.introduced_at == first_introduced_at
    with pytest.raises(EnrollmentStateError, match="retired"):
        introduce_enrollment(db, enrollment_id=enrollment.id, now=now + timedelta(minutes=5))


def test_enrollment_rejects_unpublished_card_and_disabled_owner(db: Session) -> None:
    owner = _create_owner(db)
    candidate = _publish_cards(db, count=1, status="candidate")[0]

    with pytest.raises(EnrollmentReferenceError, match="approved or published"):
        enroll_card(db, EnrollmentCreate(user_id=owner.id, card_id=candidate.id))

    published = _publish_cards(db, count=2)[1]
    owner.status = "disabled"
    db.commit()
    with pytest.raises(EnrollmentReferenceError, match="active Owner"):
        enroll_card(db, EnrollmentCreate(user_id=owner.id, card_id=published.id))


def test_enrollment_schema_rejects_invalid_priority() -> None:
    with pytest.raises(ValidationError):
        EnrollmentCreate(user_id=1, card_id=1, priority=101)
