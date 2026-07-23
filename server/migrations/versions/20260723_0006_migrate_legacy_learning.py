"""migrate prototype learning data to the personal learning domain

Revision ID: 20260723_0006
Revises: 20260722_0005
Create Date: 2026-07-23

The legacy tables remain intact for the compatibility API.  This revision only creates
the Owner/profile and copies their learning history into user-scoped tables.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0006"
down_revision: str | None = "20260722_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER_NAME = "Legacy Owner"
LEGACY_ATTEMPT_PREFIX = "legacy-review-log-"


def _utc(value: Any, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if not isinstance(value, datetime):
        return fallback
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _reflect(bind: sa.engine.Connection) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    names = (
        "users",
        "learning_profiles",
        "user_sessions",
        "books",
        "cards",
        "review_states",
        "review_logs",
        "card_enrollments",
        "card_review_states",
        "study_sessions",
        "review_attempts",
        "card_issues",
    )
    return {name: sa.Table(name, metadata, autoload_with=bind) for name in names}


def _snapshot(
    state: dict[str, Any],
    *,
    due_at: datetime,
    state_name: str | None = None,
    last_rating: int | None = None,
    last_reviewed_at: datetime | None = None,
    stability: float | None = None,
    difficulty: float | None = None,
    algorithm_version: str | None = None,
) -> dict[str, Any]:
    payload = {
        "due_at": _iso(due_at),
        "stability": float(state["stability"] if stability is None else stability),
        "difficulty": float(state["difficulty"] if difficulty is None else difficulty),
        "elapsed_days": float(state["elapsed_days"]),
        "scheduled_days": float(state["scheduled_days"]),
        "reps": int(state["reps"]),
        "lapses": int(state["lapses"]),
        "state": state["state"] if state_name is None else state_name,
        "last_rating": state.get("last_rating") if last_rating is None else last_rating,
        "last_reviewed_at": _iso(last_reviewed_at),
        "algorithm_version": state["algorithm_version"]
        if algorithm_version is None
        else algorithm_version,
    }
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _ensure_owner(
    bind: sa.engine.Connection,
    tables: dict[str, sa.Table],
    *,
    timestamp: datetime,
) -> int:
    users = tables["users"]
    profiles = tables["learning_profiles"]
    owner_id = bind.execute(
        sa.select(users.c.id).where(users.c.status == "active").limit(1)
    ).scalar_one_or_none()
    if owner_id is None:
        bind.execute(
            sa.insert(users).values(
                status="active",
                display_name=LEGACY_OWNER_NAME,
                timezone="Asia/Shanghai",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        owner_id = bind.execute(
            sa.select(users.c.id)
            .where(users.c.status == "active", users.c.display_name == LEGACY_OWNER_NAME)
            .order_by(users.c.id.desc())
            .limit(1)
        ).scalar_one()

    profile_exists = bind.execute(
        sa.select(profiles.c.id).where(profiles.c.user_id == owner_id).limit(1)
    ).scalar_one_or_none()
    if profile_exists is None:
        bind.execute(
            sa.insert(profiles).values(
                user_id=owner_id,
                goal_type="daily_learning",
                daily_minutes=20,
                study_days=[True] * 7,
                desired_retention=0.90,
                new_card_ceiling=5,
                subject_priorities={},
                initial_self_assessment={},
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return int(owner_id)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _reflect(bind)
    cards = tables["cards"]
    card_count = bind.execute(sa.select(sa.func.count()).select_from(cards)).scalar_one()
    if card_count == 0:
        return

    timestamp = datetime.now(UTC)
    owner_id = _ensure_owner(bind, tables, timestamp=timestamp)
    states_table = tables["review_states"]
    state_rows = list(bind.execute(sa.select(states_table).order_by(states_table.c.id)).mappings())
    cards_by_id = {int(row["id"]): dict(row) for row in bind.execute(sa.select(cards)).mappings()}
    enrollments = tables["card_enrollments"]
    review_states = tables["card_review_states"]
    state_by_card: dict[int, dict[str, Any]] = {}

    for raw_row in state_rows:
        row = dict(raw_row)
        card_id = int(row["card_id"])
        card = cards_by_id.get(card_id)
        if card is None:
            raise RuntimeError(f"legacy review state {row['id']} references missing card {card_id}")
        state_by_card[card_id] = row
        due_at = _utc(row["due_at"], timestamp)
        introduced_at = _utc(row.get("updated_at"), due_at)
        enrollment_id = bind.execute(
            sa.select(enrollments.c.id)
            .where(
                enrollments.c.user_id == owner_id,
                enrollments.c.card_id == card_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if enrollment_id is None:
            bind.execute(
                sa.insert(enrollments).values(
                    user_id=owner_id,
                    card_id=card_id,
                    status="active",
                    priority=50,
                    source="manual",
                    introduced_at=introduced_at,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )

        state_id = bind.execute(
            sa.select(review_states.c.id)
            .where(
                review_states.c.user_id == owner_id,
                review_states.c.card_id == card_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if state_id is None:
            bind.execute(
                sa.insert(review_states).values(
                    user_id=owner_id,
                    card_id=card_id,
                    due_at=due_at,
                    stability=float(row["stability"]),
                    difficulty=float(row["difficulty"]),
                    elapsed_days=float(row["elapsed_days"]),
                    scheduled_days=float(row["scheduled_days"]),
                    reps=int(row["reps"]),
                    lapses=int(row["lapses"]),
                    state=row["state"],
                    algorithm_version=row["algorithm_version"],
                    last_rating=row.get("last_rating"),
                    last_reviewed_at=(
                        _utc(row["last_reviewed_at"], timestamp)
                        if row.get("last_reviewed_at") is not None
                        else None
                    ),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )

    logs = tables["review_logs"]
    log_rows = list(bind.execute(sa.select(logs).order_by(logs.c.id)).mappings())
    if not log_rows:
        return

    reviewed_times = [_utc(row.get("reviewed_at"), timestamp) for row in log_rows]
    started_at = min(reviewed_times)
    ended_at = max(reviewed_times)
    session_table = tables["study_sessions"]
    session_id = bind.execute(
        sa.select(session_table.c.id)
        .where(
            session_table.c.user_id == owner_id,
            session_table.c.session_type == "review",
            session_table.c.status == "completed",
            session_table.c.planned_task_count == len(log_rows),
            session_table.c.completed_task_count == len(log_rows),
        )
        .limit(1)
    ).scalar_one_or_none()
    if session_id is None:
        elapsed_minutes = max(0, int((ended_at - started_at).total_seconds() // 60))
        session_id = bind.execute(
            sa.insert(session_table)
            .values(
                user_id=owner_id,
                session_type="review",
                status="completed",
                started_at=started_at,
                ended_at=ended_at,
                estimated_minutes=min(elapsed_minutes, 1440),
                actual_minutes=min(elapsed_minutes, 1440),
                planned_task_count=len(log_rows),
                completed_task_count=len(log_rows),
                created_at=timestamp,
                updated_at=timestamp,
            )
            .returning(session_table.c.id)
        ).scalar_one()

    attempts = tables["review_attempts"]
    for raw_log in log_rows:
        log = dict(raw_log)
        client_attempt_id = f"{LEGACY_ATTEMPT_PREFIX}{log['id']}"
        existing_attempt = bind.execute(
            sa.select(attempts.c.id)
            .where(
                attempts.c.user_id == owner_id,
                attempts.c.client_attempt_id == client_attempt_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing_attempt is not None:
            continue
        card_id = int(log["card_id"])
        state = state_by_card.get(card_id)
        if state is None:
            raise RuntimeError(f"legacy review log {log['id']} references missing state {card_id}")
        reviewed_at = _utc(log.get("reviewed_at"), timestamp)
        due_before = _utc(log.get("due_before"), _utc(state["due_at"], timestamp))
        due_after = _utc(log.get("due_after"), _utc(state["due_at"], timestamp))
        algorithm_version = log.get("algorithm_version") or state["algorithm_version"]
        before = _snapshot(
            state,
            due_at=due_before,
            state_name=log.get("state_before") or state["state"],
            last_rating=None,
            last_reviewed_at=None,
            algorithm_version=algorithm_version,
        )
        after = _snapshot(
            state,
            due_at=due_after,
            state_name=log.get("state_after") or state["state"],
            last_rating=int(log["rating"]),
            last_reviewed_at=reviewed_at,
            stability=log.get("stability_after"),
            difficulty=log.get("difficulty_after"),
            algorithm_version=algorithm_version,
        )
        bind.execute(
            sa.insert(attempts).values(
                session_id=session_id,
                user_id=owner_id,
                card_id=card_id,
                card_revision=int(cards_by_id[card_id].get("content_revision") or 1),
                client_attempt_id=client_attempt_id,
                rating=int(log["rating"]),
                response_ms=0,
                hint_used=False,
                reveal_count=0,
                answer_payload=None,
                state_before=before,
                state_after=after,
                due_before=due_before,
                due_after=due_after,
                algorithm_version=algorithm_version,
                reviewed_at=reviewed_at,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _reflect(bind)
    users = tables["users"]
    owner_ids = [
        int(value)
        for value in bind.execute(
            sa.select(users.c.id).where(users.c.display_name == LEGACY_OWNER_NAME)
        ).scalars()
    ]
    if not owner_ids:
        return

    for table_name in (
        "user_sessions",
        "card_enrollments",
        "card_review_states",
        "study_sessions",
        "review_attempts",
        "card_issues",
    ):
        table = tables[table_name]
        if "user_id" not in table.c:
            continue
        count = bind.execute(
            sa.select(sa.func.count()).select_from(table).where(table.c.user_id.in_(owner_ids))
        ).scalar_one()
        if count:
            raise RuntimeError(
                "cannot downgrade 20260723_0006 after personal learning data exists; "
                "stop the service and restore the pre-migration backup"
            )

    profiles = tables["learning_profiles"]
    bind.execute(sa.delete(profiles).where(profiles.c.user_id.in_(owner_ids)))
    bind.execute(sa.delete(users).where(users.c.id.in_(owner_ids)))
