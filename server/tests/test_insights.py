from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth import require_owner
from app.catalog.models import Book, Card, Document, DocumentChunk, DocumentVersion
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.learning.insights import (
    build_insight_summary,
    build_insight_workload,
    build_weak_topic_page,
)
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

NOW = datetime(2026, 7, 26, 16, 30, tzinfo=UTC)  # Shanghai: 2026-07-27 00:30


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
    db.execute(delete(Card).where(Card.external_id.like("insight-%")))
    db.execute(delete(Book).where(Book.name.like("Insight%")))
    db.execute(delete(Document).where(Document.document_key.like("insight-%")))
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


def _owner(db: Session) -> User:
    owner = User(status="active", timezone="Asia/Shanghai")
    db.add(owner)
    db.flush()
    db.add(
        LearningProfile(
            user_id=owner.id,
            goal_type="daily_learning",
            daily_minutes=10,
            study_days=[True] * 7,
            desired_retention=0.9,
            new_card_ceiling=5,
            subject_priorities={"方剂学": 5},
            initial_self_assessment={},
        )
    )
    db.commit()
    db.refresh(owner)
    return owner


def _card(db: Session, book: Book, *, suffix: str, tags: list[str] | None = None) -> Card:
    card = Card(
        external_id=f"insight-{suffix}",
        book_id=book.id,
        chapter="第一章",
        card_type="definition",
        question=f"问题 {suffix}",
        answer=f"答案 {suffix}",
        source_excerpt=f"来源 {suffix}",
        source_pages_json="[3]",
        status="published",
        content_revision=1,
        content_hash=f"{abs(hash(suffix)):064x}"[-64:],
        answer_points=[],
        tags=tags or ["方剂"],
    )
    db.add(card)
    db.flush()
    return card


def _enroll(
    db: Session,
    *,
    owner: User,
    card: Card,
    status: str,
    due_at: datetime | None = None,
    mastered: bool = False,
) -> None:
    db.add(
        CardEnrollment(
            user_id=owner.id,
            card_id=card.id,
            status=status,
            priority=50,
            source="manual",
            introduced_at=NOW - timedelta(days=40) if status == "active" else None,
        )
    )
    if status == "active":
        db.add(
            CardReviewState(
                user_id=owner.id,
                card_id=card.id,
                due_at=due_at or NOW,
                stability=10 if mastered else 1,
                difficulty=5,
                elapsed_days=1,
                scheduled_days=2,
                reps=3 if mastered else 1,
                lapses=0,
                state="review" if mastered else "learning",
                algorithm_version="fsrs-v1",
                last_rating=3 if mastered else 2,
                last_reviewed_at=NOW - timedelta(days=1),
            )
        )


def _attempt(
    db: Session,
    *,
    owner: User,
    session: StudySession,
    card: Card,
    suffix: str,
    rating: int,
    reviewed_at: datetime,
    was_new: bool = False,
) -> None:
    db.add(
        ReviewAttempt(
            session_id=session.id,
            user_id=owner.id,
            card_id=card.id,
            card_revision=1,
            client_attempt_id=f"insight-{suffix}",
            rating=rating,
            response_ms=30_000,
            hint_used=False,
            reveal_count=0,
            state_before={"state": "new" if was_new else "review"},
            state_after={"state": "review"},
            due_before=reviewed_at,
            due_after=reviewed_at + timedelta(days=2),
            algorithm_version="fsrs-v1",
            reviewed_at=reviewed_at,
        )
    )


def test_empty_insight_read_models_and_http_contract(db: Session) -> None:
    owner = _owner(db)
    summary = build_insight_summary(db, user_id=owner.id, now=NOW)
    workload = build_insight_workload(db, user_id=owner.id, now=NOW)
    weak = build_weak_topic_page(db, user_id=owner.id, now=NOW)
    assert summary.local_date == "2026-07-27"
    assert summary.study_days == 0
    assert summary.content.document_page_count == 0
    assert summary.content.published_card_count == 0
    assert summary.subjects == []
    assert len(workload.days) == 7
    assert workload.total_due_count == 0
    assert workload.total_budget_minutes == 70
    assert weak.total == 0 and weak.items == [] and weak.has_more is False

    app.dependency_overrides[require_owner] = lambda: owner
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            paths = (
                "/api/v1/insights/summary",
                "/api/v1/insights/workload",
                "/api/v1/insights/weak-topics",
            )
            responses = [client.get(path) for path in paths]
        assert [response.status_code for response in responses] == [200, 200, 200]
    finally:
        app.dependency_overrides.pop(require_owner, None)


def test_small_data_cross_timezone_counts_workload_and_subject_trend(db: Session) -> None:
    owner = _owner(db)
    document = Document(
        document_key="insight-doc",
        title="洞察文档",
        subject="方剂学",
        copyright_scope="personal_use",
    )
    db.add(document)
    db.flush()
    version = DocumentVersion(
        document_id=document.id,
        source_sha256="a" * 64,
        source_file_name="insight.pdf",
        page_count=10,
        size_bytes=100,
        processing_version="v1",
        status="published",
    )
    db.add(version)
    db.flush()
    db.add(
        DocumentChunk(
            document_version_id=version.id,
            chunk_key="insight-pages",
            chapter_path=["第一章"],
            pdf_page_index_start=0,
            pdf_page_index_end=5,
            printed_page_labels=[],
            block_type="paragraph",
            source_text="source",
            cleaned_text="clean",
            content_hash="b" * 64,
            quality_status="ready",
            quality_flags=[],
            pipeline_version="v1",
        )
    )
    book = Book(name="Insight Book", subject="方剂学")
    db.add(book)
    db.flush()
    mastered = _card(db, book, suffix="mastered")
    backlog = _card(db, book, suffix="backlog")
    queued = _card(db, book, suffix="queued")
    _card(db, book, suffix="unenrolled")
    _enroll(
        db,
        owner=owner,
        card=mastered,
        status="active",
        due_at=NOW + timedelta(days=2),
        mastered=True,
    )
    _enroll(
        db,
        owner=owner,
        card=backlog,
        status="active",
        due_at=NOW - timedelta(days=2),
    )
    _enroll(db, owner=owner, card=queued, status="queued")
    session = StudySession(
        user_id=owner.id,
        session_type="daily",
        status="completed",
        started_at=NOW - timedelta(minutes=10),
        ended_at=NOW - timedelta(minutes=5),
        estimated_minutes=8,
        actual_minutes=8,
        planned_task_count=4,
        completed_task_count=4,
    )
    previous_session = StudySession(
        user_id=owner.id,
        session_type="daily",
        status="completed",
        started_at=datetime(2026, 7, 26, 15, 40, tzinfo=UTC),
        ended_at=datetime(2026, 7, 26, 15, 50, tzinfo=UTC),
        estimated_minutes=6,
        actual_minutes=6,
        planned_task_count=1,
        completed_task_count=1,
    )
    db.add_all([session, previous_session])
    db.flush()
    _attempt(
        db,
        owner=owner,
        session=session,
        card=mastered,
        suffix="today",
        rating=3,
        reviewed_at=datetime(2026, 7, 26, 16, 10, tzinfo=UTC),
    )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=mastered,
        suffix="recent",
        rating=3,
        reviewed_at=NOW - timedelta(days=2),
    )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=mastered,
        suffix="old-1",
        rating=1,
        reviewed_at=NOW - timedelta(days=20),
        was_new=True,
    )
    _attempt(
        db,
        owner=owner,
        session=session,
        card=mastered,
        suffix="old-2",
        rating=1,
        reviewed_at=NOW - timedelta(days=21),
    )
    db.commit()

    summary = build_insight_summary(db, user_id=owner.id, now=NOW)
    assert summary.local_date == "2026-07-27"
    assert summary.today_review_count == 1
    assert summary.today_actual_minutes == 8
    assert summary.total_review_count == 4
    assert summary.total_new_count == 1
    assert summary.total_actual_minutes == 14
    assert summary.study_days == 5
    assert summary.current_due_count == 1
    assert summary.backlog_count == 1
    assert summary.content.document_page_count == 10
    assert summary.content.covered_page_count == 6
    assert summary.content.coverage_ratio == 0.6
    assert summary.content.published_card_count == 4
    assert summary.content.enrolled_card_count == 3
    assert summary.content.active_card_count == 2
    assert summary.content.mastered_card_count == 1
    subject = summary.subjects[0]
    assert subject.subject == "方剂学"
    assert subject.trend == "improving"
    assert subject.success_rate_30d == 0.5

    workload = build_insight_workload(db, user_id=owner.id, now=NOW)
    assert workload.days[0].local_date == "2026-07-27"
    assert workload.days[0].due_count == 1
    assert workload.days[0].overdue_count == 1
    assert workload.days[2].due_count == 1
    assert workload.total_due_count == 2


def test_large_weak_topic_offset_pagination_is_stable(db: Session) -> None:
    owner = _owner(db)
    book = Book(name="Insight Pagination", subject="中药学")
    db.add(book)
    db.flush()
    for index in range(35):
        card = _card(db, book, suffix=f"page-{index:02d}", tags=[f"标签 {index:02d}"])
        _enroll(db, owner=owner, card=card, status="active", due_at=NOW + timedelta(days=30))
        db.add(
            CardIssue(
                user_id=owner.id,
                card_id=card.id,
                card_revision=1,
                issue_type="too_large",
                details="需要拆分",
                status="open",
                created_at=NOW,
            )
        )
    db.commit()

    first = build_weak_topic_page(db, user_id=owner.id, offset=0, limit=20, now=NOW)
    second = build_weak_topic_page(db, user_id=owner.id, offset=20, limit=20, now=NOW)
    replay = build_weak_topic_page(db, user_id=owner.id, offset=0, limit=20, now=NOW)
    first_ids = [item.card_id for item in first.items]
    second_ids = [item.card_id for item in second.items]
    assert first.total == 35 and second.total == 35
    assert len(first_ids) == 20 and len(second_ids) == 15
    assert first.has_more is True and second.has_more is False
    assert not set(first_ids) & set(second_ids)
    assert first_ids == [item.card_id for item in replay.items]
