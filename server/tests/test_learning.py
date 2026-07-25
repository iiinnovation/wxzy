from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.catalog.schemas import (
    CardSourceCreate,
    CatalogCardCreate,
    ChapterCreate,
    ChunkQualityStatus,
    DocumentChunkCreate,
    DocumentCreate,
    DocumentVersionCreate,
)
from app.catalog.services import (
    create_catalog_card,
    create_chapter,
    create_document_chunk,
    register_document_version,
)
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.learning.models import CardEnrollment, CardReviewState
from app.learning.schemas import (
    EnrollmentCreate,
    EnrollmentRequest,
    EnrollmentScope,
    EnrollmentSource,
    EnrollmentStatus,
)
from app.learning.services import (
    EnrollmentReferenceError,
    EnrollmentStateError,
    change_enrollment_status,
    enroll_book,
    enroll_card,
    enroll_chapter,
    enroll_scope,
    introduce_enrollment,
    list_due_review_states,
    list_queued_enrollments,
)


def _clean_learning_rows(db: Session) -> None:
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(CardSource))
    db.execute(delete(Card).where(Card.external_id.like("learning-test-%")))
    db.execute(delete(DocumentChunk).where(DocumentChunk.chunk_key.like("learning-test-%")))
    db.execute(delete(Chapter).where(Chapter.chapter_key.like("learning-test-%")))
    db.execute(delete(DocumentVersion))
    db.execute(delete(Document).where(Document.document_key.like("learning-test-%")))
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


def _publish_catalog_chapter_cards(db: Session) -> tuple[Book, Chapter, Chapter, list[Card]]:
    book = Book(name="Learning Test Catalog Book", subject="方剂学")
    db.add(book)
    db.flush()
    registration = register_document_version(
        db,
        document_values=DocumentCreate(
            document_key="learning-test-fangji",
            title="学霸笔记-方剂学",
            subject="方剂学",
        ),
        version_values=DocumentVersionCreate(
            source_sha256="d" * 64,
            source_file_name="fangji.pdf",
            page_count=40,
            size_bytes=1024,
            processing_version="pipeline-v2",
        ),
        now=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
    )
    version = registration.version
    early = create_chapter(
        db,
        ChapterCreate(
            document_version_id=version.id,
            chapter_key="learning-test-ch-01",
            title="第一章",
            level=1,
            sort_order=1,
            pdf_page_index_start=0,
            pdf_page_index_end=9,
            recognition_method="heading_layout",
        ),
    )
    later = create_chapter(
        db,
        ChapterCreate(
            document_version_id=version.id,
            chapter_key="learning-test-ch-02",
            title="第二章",
            level=1,
            sort_order=2,
            pdf_page_index_start=10,
            pdf_page_index_end=19,
            recognition_method="heading_layout",
        ),
    )
    cards: list[Card] = []
    for index, (chapter, page) in enumerate(
        [(later, 12), (early, 3), (early, 5), (later, 15)],
        start=1,
    ):
        chunk = create_document_chunk(
            db,
            DocumentChunkCreate(
                document_version_id=version.id,
                chapter_id=chapter.id,
                chunk_key=f"learning-test-chunk-{index}",
                chapter_path=["方剂学", chapter.title],
                pdf_page_index_start=page,
                pdf_page_index_end=page,
                printed_page_labels=[str(page + 1)],
                block_type="paragraph",
                source_text=f"source {index}",
                cleaned_text=f"clean {index}",
                content_hash=f"{index:064x}"[-64:],
                quality_status=ChunkQualityStatus.READY,
                quality_flags=[],
                pipeline_version="pipeline-v2",
            ),
        )
        card = create_catalog_card(
            db,
            CatalogCardCreate(
                external_id=f"learning-test-catalog-{index}",
                book_id=book.id,
                card_type="definition",
                question=f"问题 {index}",
                answer=f"答案 {index}",
                content_revision=1,
                content_hash=f"{(index + 20):064x}"[-64:],
                answer_points=[f"要点 {index}"],
                tags=["方剂学"],
                sources=[
                    CardSourceCreate(
                        document_chunk_id=chunk.id,
                        citation_order=0,
                        excerpt=f"摘录 {index}",
                        pdf_page_index_start=page,
                        pdf_page_index_end=page,
                    )
                ],
            ),
        )
        cards.append(card)
    # candidate card in early chapter must stay out of enrollment
    candidate_chunk = create_document_chunk(
        db,
        DocumentChunkCreate(
            document_version_id=version.id,
            chapter_id=early.id,
            chunk_key="learning-test-chunk-candidate",
            chapter_path=["方剂学", early.title],
            pdf_page_index_start=6,
            pdf_page_index_end=6,
            printed_page_labels=["7"],
            block_type="paragraph",
            source_text="candidate source",
            cleaned_text="candidate clean",
            content_hash="e" * 64,
            quality_status=ChunkQualityStatus.READY,
            quality_flags=[],
            pipeline_version="pipeline-v2",
        ),
    )
    candidate = create_catalog_card(
        db,
        CatalogCardCreate(
            external_id="learning-test-catalog-candidate",
            book_id=book.id,
            card_type="definition",
            question="候选问题",
            answer="候选答案",
            content_revision=1,
            content_hash="f" * 64,
            answer_points=["候选"],
            tags=["方剂学"],
            sources=[
                CardSourceCreate(
                    document_chunk_id=candidate_chunk.id,
                    citation_order=0,
                    excerpt="候选摘录",
                    pdf_page_index_start=6,
                    pdf_page_index_end=6,
                )
            ],
        ),
    )
    candidate.status = "candidate"
    db.commit()
    return book, early, later, cards


def test_enroll_chapter_is_idempotent_and_does_not_create_due(db: Session) -> None:
    owner = _create_owner(db)
    _book, early, _later, cards = _publish_catalog_chapter_cards(db)
    now = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)

    first = enroll_chapter(db, user_id=owner.id, chapter_id=early.id, priority=70, now=now)
    second = enroll_chapter(db, user_id=owner.id, chapter_id=early.id, priority=10, now=now)

    early_card_ids = {cards[1].id, cards[2].id}
    assert first.created_count == 2
    assert first.existing_count == 0
    assert set(first.card_ids) == early_card_ids
    assert first.card_ids == [cards[1].id, cards[2].id]
    assert second.created_count == 0
    assert second.existing_count == 2
    assert second.card_ids == first.card_ids
    assert {row.id for row in second.enrollments} == {row.id for row in first.enrollments}
    assert all(row.status == "queued" for row in first.enrollments)
    assert all(row.source == "chapter" for row in first.enrollments)
    assert all(row.priority == 70 for row in second.enrollments)
    assert db.scalar(select(func.count()).select_from(CardEnrollment)) == 2
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 0
    assert list_due_review_states(db, user_id=owner.id, now=now) == []


def test_enroll_book_orders_by_chapter_and_suspend_excludes_due(db: Session) -> None:
    owner = _create_owner(db)
    book, _early, _later, cards = _publish_catalog_chapter_cards(db)
    now = datetime(2026, 7, 22, 7, 0, tzinfo=UTC)

    result = enroll_book(db, user_id=owner.id, book_id=book.id, priority=60, now=now)
    assert result.created_count == 4
    assert result.card_ids == [cards[1].id, cards[2].id, cards[0].id, cards[3].id]
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 0
    assert list_due_review_states(db, user_id=owner.id, now=now) == []

    queued = list_queued_enrollments(db, user_id=owner.id)
    assert [row.card_id for row in queued] == result.card_ids

    # introduce first two; suspend one; remaining queued stay non-due
    first = introduce_enrollment(db, enrollment_id=queued[0].id, now=now)
    second = introduce_enrollment(db, enrollment_id=queued[1].id, now=now)
    change_enrollment_status(
        db,
        enrollment_id=first.enrollment.id,
        target_status=EnrollmentStatus.SUSPENDED,
        now=now + timedelta(minutes=1),
    )

    due = list_due_review_states(db, user_id=owner.id, now=now)
    assert [state.card_id for state in due] == [second.enrollment.card_id]
    assert db.get(CardReviewState, first.review_state.id) is not None
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 2
    assert (
        db.scalar(
            select(func.count())
            .select_from(CardEnrollment)
            .where(CardEnrollment.status == "queued")
        )
        == 2
    )


def test_enroll_scope_card_matches_manual_enroll(db: Session) -> None:
    owner = _create_owner(db)
    card = _publish_cards(db, count=1)[0]
    now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    result = enroll_scope(
        db,
        EnrollmentRequest(
            scope=EnrollmentScope.CARD,
            card_id=card.id,
            priority=55,
        ).to_scope_create(user_id=owner.id),
        now=now,
    )
    assert result.scope == EnrollmentScope.CARD
    assert result.created_count == 1
    assert result.enrollments[0].source == "manual"
    assert result.enrollments[0].status == "queued"
    assert list_due_review_states(db, user_id=owner.id, now=now) == []


def test_enrollment_request_schema_requires_single_target() -> None:
    with pytest.raises(ValidationError):
        EnrollmentRequest(scope=EnrollmentScope.BOOK, book_id=1, chapter_id=2)
    with pytest.raises(ValidationError):
        EnrollmentRequest(scope=EnrollmentScope.CHAPTER)
