from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import GoalType, LearningProfileValues, OwnerCreate
from app.identity.services import (
    ActiveOwnerExistsError,
    create_owner_with_default_profile,
    update_learning_profile,
)


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        session.execute(delete(UserSession))
        session.execute(delete(LearningProfileAudit))
        session.execute(delete(LearningProfile))
        session.execute(delete(User))
        session.commit()
        yield session
        session.rollback()


def test_owner_creation_builds_default_profile_with_utc_fields(db: Session) -> None:
    now = datetime(2026, 7, 22, 8, 30, tzinfo=UTC)

    owner = create_owner_with_default_profile(
        db, OwnerCreate(display_name="  Owner  ", timezone="Asia/Shanghai"), now=now
    )
    profile = owner.learning_profile

    assert owner.display_name == "Owner"
    assert owner.status == "active"
    assert owner.created_at == now
    assert owner.created_at.tzinfo is UTC
    assert profile is not None
    assert profile.goal_type == "daily_learning"
    assert profile.daily_minutes == 20
    assert profile.study_days == [True] * 7
    assert profile.desired_retention == pytest.approx(0.90)
    assert profile.new_card_ceiling == 5
    assert profile.subject_priorities == {}
    assert profile.initial_self_assessment == {}
    assert profile.onboarding_completed_at is None
    assert profile.created_at == now
    assert profile.created_at.tzinfo is UTC


def test_database_rejects_a_second_active_owner_but_allows_disabled_history(
    db: Session,
) -> None:
    create_owner_with_default_profile(db, OwnerCreate())
    db.add(User(status="active", timezone="UTC"))

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(User(status="disabled", timezone="UTC"))
    db.add(User(status="disabled", timezone="Asia/Shanghai"))
    db.commit()
    assert db.scalar(select(func.count()).select_from(User)) == 3


def test_owner_service_reports_active_owner_conflict(db: Session) -> None:
    first = create_owner_with_default_profile(db, OwnerCreate())

    with pytest.raises(ActiveOwnerExistsError):
        create_owner_with_default_profile(db, OwnerCreate(timezone="UTC"))

    assert db.scalar(select(User.id).where(User.status == "active")) == first.id
    assert db.scalar(select(func.count()).select_from(LearningProfile)) == 1


def test_profile_update_preserves_stable_rows_and_session_history(db: Session) -> None:
    created_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
    updated_at = created_at + timedelta(hours=1)
    owner = create_owner_with_default_profile(db, OwnerCreate(), now=created_at)
    assert owner.learning_profile is not None
    profile_id = owner.learning_profile.id
    session = UserSession(
        user_id=owner.id,
        token_hash="a" * 64,
        expires_at=created_at + timedelta(days=30),
        created_at=created_at,
    )
    db.add(session)
    db.commit()
    session_id = session.id

    profile = update_learning_profile(
        db,
        user_id=owner.id,
        values=LearningProfileValues(
            goal_type=GoalType.EXAM,
            target_date=date(2026, 12, 1),
            daily_minutes=45,
            study_days=[True, True, True, True, True, False, False],
            desired_retention=0.93,
            new_card_ceiling=8,
            subject_priorities={"方剂学": 5},
            initial_self_assessment={"方剂学": 2},
        ),
        now=updated_at,
    )

    assert profile.id == profile_id
    assert profile.created_at == created_at
    assert profile.updated_at == updated_at
    assert profile.daily_minutes == 45
    assert db.get(UserSession, session_id) is not None
    assert db.get(User, owner.id) is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("daily_minutes", 4),
        ("daily_minutes", 241),
        ("study_days", [True] * 6),
        ("study_days", [False] * 7),
        ("desired_retention", 0.69),
        ("desired_retention", 1.0),
        ("new_card_ceiling", -1),
        ("subject_priorities", {"方剂学": 6}),
        ("initial_self_assessment", {" ": 3}),
    ],
)
def test_learning_profile_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        LearningProfileValues(**{field: value})


def test_owner_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="IANA timezone"):
        OwnerCreate(timezone="Mars/Olympus_Mons")
