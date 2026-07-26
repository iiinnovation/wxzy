from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import require_owner
from app.catalog.models import Book, Card
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.learning.coach import build_repair_suggestions
from app.learning.models import (
    CardEnrollment,
    CardIssue,
    CardReviewState,
    DailyPlan,
    DailyPlanItem,
    ReviewAttempt,
    StudySession,
)
from app.main import app

BASE_TIME = datetime(2026, 7, 26, 2, 0, tzinfo=UTC)


def _clean(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(StudySession))
    db.execute(delete(DailyPlanItem))
    db.execute(delete(DailyPlan))
    db.execute(delete(CardIssue))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("repair-rules-%")))
    db.execute(delete(Book).where(Book.name.like("Repair Rules%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    session = Session(engine)
    _clean(session)
    try:
        yield session
    finally:
        session.close()
        with Session(engine) as cleanup:
            _clean(cleanup)


def _seed_context(db: Session) -> tuple[User, StudySession, dict[str, Card]]:
    owner = User(status="active", timezone="Asia/Shanghai")
    book = Book(name="Repair Rules Book", subject="方剂学")
    db.add_all([owner, book])
    db.flush()
    cards: dict[str, Card] = {}
    tags_by_name = {
        "again": ["温里剂"],
        "slow_hard": ["补益剂"],
        "confusion_a": ["相似方剂"],
        "confusion_b": ["相似方剂"],
        "issue": ["清热剂"],
        "one_again": ["单次错误"],
        "fast_hard": ["快速困难"],
        "lone_tag": ["独立标签"],
    }
    for index, (name, tags) in enumerate(tags_by_name.items(), start=1):
        card = Card(
            external_id=f"repair-rules-{name}",
            book_id=book.id,
            chapter=f"章节 {index}",
            section=f"小节 {index}",
            card_type="definition",
            question=f"问题 {name}",
            answer=f"答案 {name}",
            source_excerpt=f"原文证据 {name}",
            source_pages_json=json.dumps([10 + index, 11 + index]),
            status="published",
            content_revision=1,
            content_hash=f"{index:064x}",
            answer_points=[],
            tags=tags,
        )
        db.add(card)
        db.flush()
        db.add(
            CardEnrollment(
                user_id=owner.id,
                card_id=card.id,
                status="active",
                priority=50,
                source="manual",
                introduced_at=BASE_TIME - timedelta(days=60),
            )
        )
        cards[name] = card
    session = StudySession(
        user_id=owner.id,
        session_type="review",
        status="completed",
        started_at=BASE_TIME - timedelta(days=5, minutes=20),
        ended_at=BASE_TIME - timedelta(days=5),
        estimated_minutes=20,
        actual_minutes=20,
        planned_task_count=20,
        completed_task_count=20,
    )
    db.add(session)
    db.commit()
    db.refresh(owner)
    db.refresh(session)
    return owner, session, cards


def _attempt(
    db: Session,
    *,
    owner: User,
    session: StudySession,
    card: Card,
    suffix: str,
    rating: int,
    response_ms: int,
    days_ago: int,
) -> None:
    reviewed_at = BASE_TIME - timedelta(days=days_ago)
    db.add(
        ReviewAttempt(
            session_id=session.id,
            user_id=owner.id,
            card_id=card.id,
            card_revision=card.content_revision,
            client_attempt_id=f"repair-{card.id}-{suffix}",
            rating=rating,
            response_ms=response_ms,
            hint_used=False,
            reveal_count=0,
            answer_payload=None,
            state_before={},
            state_after={},
            due_before=reviewed_at,
            due_after=reviewed_at + timedelta(days=1),
            algorithm_version="fsrs-v1",
            reviewed_at=reviewed_at,
        )
    )


def _seed_signals(db: Session, owner: User, session: StudySession, cards: dict[str, Card]) -> None:
    _attempt(
        db,
        owner=owner,
        session=session,
        card=cards["again"],
        suffix="again-1",
        rating=1,
        response_ms=20_000,
        days_ago=2,
    )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=cards["again"],
        suffix="again-2",
        rating=1,
        response_ms=25_000,
        days_ago=1,
    )
    for index, days_ago in enumerate((4, 2), start=1):
        _attempt(
            db,
            owner=owner,
            session=session,
            card=cards["slow_hard"],
            suffix=f"slow-{index}",
            rating=2,
            response_ms=75_000,
            days_ago=days_ago,
        )
    for name in ("confusion_a", "confusion_b"):
        _attempt(
            db,
            owner=owner,
            session=session,
            card=cards[name],
            suffix="confused",
            rating=2,
            response_ms=30_000,
            days_ago=3,
        )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=cards["one_again"],
        suffix="only",
        rating=1,
        response_ms=20_000,
        days_ago=1,
    )
    for index in range(2):
        _attempt(
            db,
            owner=owner,
            session=session,
            card=cards["fast_hard"],
            suffix=f"fast-{index}",
            rating=2,
            response_ms=15_000,
            days_ago=index + 1,
        )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=cards["lone_tag"],
        suffix="lone",
        rating=2,
        response_ms=20_000,
        days_ago=1,
    )
    db.add_all(
        [
            CardIssue(
                user_id=owner.id,
                card_id=cards["issue"].id,
                card_revision=1,
                issue_type="source_error",
                details="来源需要核对",
                status="open",
                created_at=BASE_TIME - timedelta(days=1),
            ),
            CardIssue(
                user_id=owner.id,
                card_id=cards["issue"].id,
                card_revision=1,
                issue_type="too_large",
                details="卡片过大",
                status="in_review",
                created_at=BASE_TIME - timedelta(days=1),
            ),
            CardIssue(
                user_id=owner.id,
                card_id=cards["one_again"].id,
                card_revision=1,
                issue_type="unclear",
                details="已处理",
                status="resolved",
                created_at=BASE_TIME - timedelta(days=10),
                resolved_at=BASE_TIME - timedelta(days=9),
            ),
        ]
    )
    db.commit()


def test_repair_rules_trigger_without_false_positives_and_point_to_source(db: Session) -> None:
    owner, session, cards = _seed_context(db)
    _seed_signals(db, owner, session, cards)
    card_count = db.scalar(select(func.count()).select_from(Card))

    result = build_repair_suggestions(db, user_id=owner.id, now=BASE_TIME)
    by_id = {item.card_id: item for item in result.items}

    expected = {
        cards[name].id for name in ("again", "slow_hard", "confusion_a", "confusion_b", "issue")
    }
    assert set(by_id) == expected
    assert cards["one_again"].id not in by_id
    assert cards["fast_hard"].id not in by_id
    assert cards["lone_tag"].id not in by_id

    again = by_id[cards["again"].id]
    assert again.reason_code == "REPAIR_REPEATED_AGAIN"
    assert again.evidence.again_count == 2
    assert [action.code for action in again.actions] == ["reread_source"]

    slow = by_id[cards["slow_hard"].id]
    assert slow.reason_code == "WEAK_SLOW_HARD"
    assert slow.evidence.slow_hard_count == 2
    assert [action.code for action in slow.actions] == ["written_recall"]

    confusion = by_id[cards["confusion_a"].id]
    assert confusion.evidence.confusion_tags == ["相似方剂"]
    assert confusion.evidence.related_card_ids == [cards["confusion_b"].id]
    assert confusion.topic == "相似方剂"
    assert confusion.actions[0].code == "compare_cards"

    issue = by_id[cards["issue"].id]
    assert issue.evidence.issue_types == ["source_error", "too_large"]
    assert [action.code for action in issue.actions] == ["review_content", "split_card"]
    assert issue.source.book_name == "Repair Rules Book"
    assert issue.source.chapter == cards["issue"].chapter
    assert issue.source.excerpt == "原文证据 issue"
    assert issue.source.pdf_page_start is not None
    assert db.scalar(select(func.count()).select_from(Card)) == card_count


def test_repair_suggestions_http_contract(db: Session) -> None:
    owner, session, cards = _seed_context(db)
    _seed_signals(db, owner, session, cards)
    app.dependency_overrides[require_owner] = lambda: owner
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/learning/repair-suggestions?limit=2")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_id"] == owner.id
        assert body["lookback_days"] == 30
        assert len(body["items"]) == 2
        assert body["items"][0]["source"]["book_name"] == "Repair Rules Book"
        assert body["items"][0]["reason_code"].startswith(("REPAIR_", "WEAK_"))
    finally:
        app.dependency_overrides.pop(require_owner, None)
