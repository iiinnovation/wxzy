from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..learning.models import (
    CardEnrollment,
    CardIssue,
    CardReviewState,
    DailyPlan,
    DailyPlanItem,
    ReviewAttempt,
    StudySession,
)
from .models import (
    LearningProfile,
    LearningProfileAudit,
    OwnerActivationCode,
    User,
    UserSession,
)
from .schemas_auth import SessionDeviceOut


class OwnerAccountReferenceError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _session_out(
    row: UserSession,
    *,
    current_session_id: int | None,
    now: datetime,
) -> SessionDeviceOut:
    status: Literal["active", "expired", "revoked"]
    if row.revoked_at is not None:
        status = "revoked"
    elif row.expires_at <= now:
        status = "expired"
    else:
        status = "active"
    return SessionDeviceOut(
        id=row.id,
        device_label=row.device_label,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        status=status,
        current=row.id == current_session_id,
    )


def list_owner_sessions(
    db: Session,
    *,
    user_id: int,
    current_session_id: int | None = None,
    now: datetime | None = None,
) -> list[SessionDeviceOut]:
    timestamp = now.astimezone(UTC) if now is not None else _utc_now()
    rows = list(
        db.scalars(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc(), UserSession.id.desc())
        )
    )
    return [_session_out(row, current_session_id=current_session_id, now=timestamp) for row in rows]


def revoke_owner_session(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    now: datetime | None = None,
) -> None:
    row = db.get(UserSession, session_id)
    if row is None or row.user_id != user_id:
        raise OwnerAccountReferenceError("session does not exist")
    if row.revoked_at is None:
        row.revoked_at = now.astimezone(UTC) if now is not None else _utc_now()
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise


def _values(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def export_owner_learning_data(db: Session, *, user_id: int) -> dict[str, list[dict[str, Any]]]:
    profile_audits = list(
        db.scalars(
            select(LearningProfileAudit)
            .where(LearningProfileAudit.user_id == user_id)
            .order_by(LearningProfileAudit.id)
        )
    )
    enrollments = list(
        db.scalars(
            select(CardEnrollment)
            .where(CardEnrollment.user_id == user_id)
            .order_by(CardEnrollment.id)
        )
    )
    review_states = list(
        db.scalars(
            select(CardReviewState)
            .where(CardReviewState.user_id == user_id)
            .order_by(CardReviewState.id)
        )
    )
    study_sessions = list(
        db.scalars(
            select(StudySession).where(StudySession.user_id == user_id).order_by(StudySession.id)
        )
    )
    attempts = list(
        db.scalars(
            select(ReviewAttempt).where(ReviewAttempt.user_id == user_id).order_by(ReviewAttempt.id)
        )
    )
    issues = list(
        db.scalars(select(CardIssue).where(CardIssue.user_id == user_id).order_by(CardIssue.id))
    )
    plans = list(
        db.scalars(select(DailyPlan).where(DailyPlan.user_id == user_id).order_by(DailyPlan.id))
    )
    plan_ids = [row.id for row in plans]
    plan_items = (
        list(
            db.scalars(
                select(DailyPlanItem)
                .where(DailyPlanItem.plan_id.in_(plan_ids))
                .order_by(DailyPlanItem.plan_id, DailyPlanItem.position)
            )
        )
        if plan_ids
        else []
    )
    return {
        "learning_profile_audits": [
            _values(
                row,
                (
                    "id",
                    "profile_id",
                    "changed_fields",
                    "before_values",
                    "after_values",
                    "created_at",
                ),
            )
            for row in profile_audits
        ],
        "enrollments": [
            _values(
                row,
                (
                    "id",
                    "card_id",
                    "status",
                    "priority",
                    "source",
                    "introduced_at",
                    "created_at",
                    "updated_at",
                ),
            )
            for row in enrollments
        ],
        "review_states": [
            _values(
                row,
                (
                    "id",
                    "card_id",
                    "due_at",
                    "stability",
                    "difficulty",
                    "elapsed_days",
                    "scheduled_days",
                    "reps",
                    "lapses",
                    "state",
                    "algorithm_version",
                    "last_rating",
                    "last_reviewed_at",
                    "created_at",
                    "updated_at",
                ),
            )
            for row in review_states
        ],
        "study_sessions": [
            _values(
                row,
                (
                    "id",
                    "session_type",
                    "status",
                    "started_at",
                    "ended_at",
                    "estimated_minutes",
                    "actual_minutes",
                    "planned_task_count",
                    "completed_task_count",
                    "interruption_reason",
                    "daily_plan_id",
                    "plan_date",
                    "cursor_position",
                    "active_started_at",
                    "created_at",
                    "updated_at",
                ),
            )
            for row in study_sessions
        ],
        "review_attempts": [
            _values(
                row,
                (
                    "id",
                    "session_id",
                    "card_id",
                    "card_revision",
                    "client_attempt_id",
                    "rating",
                    "response_ms",
                    "hint_used",
                    "reveal_count",
                    "answer_payload",
                    "state_before",
                    "state_after",
                    "due_before",
                    "due_after",
                    "algorithm_version",
                    "reviewed_at",
                ),
            )
            for row in attempts
        ],
        "card_issues": [
            _values(
                row,
                (
                    "id",
                    "card_id",
                    "card_revision",
                    "issue_type",
                    "details",
                    "status",
                    "created_at",
                    "resolved_at",
                ),
            )
            for row in issues
        ],
        "daily_plans": [
            _values(
                row,
                (
                    "id",
                    "plan_date",
                    "budget_minutes",
                    "adjusted_budget_minutes",
                    "estimated_minutes",
                    "due_count",
                    "new_count",
                    "weak_count",
                    "generation_version",
                    "is_initial",
                    "forecast_minutes_7d",
                    "forecast_budget_7d",
                    "new_cards_paused",
                    "pause_reasons",
                    "plan_reasons",
                    "generated_at",
                    "created_at",
                    "updated_at",
                ),
            )
            for row in plans
        ],
        "daily_plan_items": [
            _values(
                row,
                (
                    "id",
                    "plan_id",
                    "position",
                    "item_type",
                    "enrollment_id",
                    "card_id",
                    "estimated_seconds",
                    "reason_code",
                    "reason_detail",
                    "status",
                    "created_at",
                ),
            )
            for row in plan_items
        ],
    }


def delete_owner_account(db: Session, *, user_id: int) -> None:
    owner = db.get(User, user_id)
    if owner is None:
        raise OwnerAccountReferenceError("Owner does not exist")
    try:
        plan_ids = select(DailyPlan.id).where(DailyPlan.user_id == user_id)
        db.execute(delete(ReviewAttempt).where(ReviewAttempt.user_id == user_id))
        db.execute(delete(StudySession).where(StudySession.user_id == user_id))
        db.execute(delete(DailyPlanItem).where(DailyPlanItem.plan_id.in_(plan_ids)))
        db.execute(delete(DailyPlan).where(DailyPlan.user_id == user_id))
        db.execute(delete(CardIssue).where(CardIssue.user_id == user_id))
        db.execute(delete(CardReviewState).where(CardReviewState.user_id == user_id))
        db.execute(delete(CardEnrollment).where(CardEnrollment.user_id == user_id))
        db.execute(delete(LearningProfileAudit).where(LearningProfileAudit.user_id == user_id))
        db.execute(delete(LearningProfile).where(LearningProfile.user_id == user_id))
        db.execute(delete(OwnerActivationCode).where(OwnerActivationCode.user_id == user_id))
        db.execute(delete(UserSession).where(UserSession.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
    except Exception:
        db.rollback()
        raise


def learning_profile_values(profile: LearningProfile) -> dict[str, Any]:
    return _values(
        profile,
        (
            "goal_type",
            "target_date",
            "daily_minutes",
            "study_days",
            "desired_retention",
            "new_card_ceiling",
            "subject_priorities",
            "initial_self_assessment",
            "onboarding_completed_at",
            "created_at",
            "updated_at",
        ),
    )
