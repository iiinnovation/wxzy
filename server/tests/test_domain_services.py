from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.catalog.models import Book, Card
from app.catalog.services import card_to_out, list_books, list_cards
from app.core.errors import InvalidRequestError
from app.db import engine
from app.learning.models import CardEnrollment, CardReviewState
from app.learning.services import answer_review, list_due, stats
from app.models import ReviewLog, ReviewState
from app.publishing.services import import_payload

BOOK_PREFIX = "Domain Service Test"
CARD_PREFIX = "domain-service-test-"


def _clean_rows(db: Session) -> None:
    card_ids = (
        select(Card.id)
        .join(Book)
        .where((Card.external_id.like(f"{CARD_PREFIX}%")) | (Book.name.like(f"{BOOK_PREFIX}%")))
    )
    db.execute(delete(ReviewLog).where(ReviewLog.card_id.in_(card_ids)))
    db.execute(delete(ReviewState).where(ReviewState.card_id.in_(card_ids)))
    db.execute(delete(CardReviewState).where(CardReviewState.card_id.in_(card_ids)))
    db.execute(delete(CardEnrollment).where(CardEnrollment.card_id.in_(card_ids)))
    db.execute(delete(Card).where(Card.id.in_(card_ids)))
    db.execute(delete(Book).where((Book.name.like(f"{BOOK_PREFIX}%")) | (Book.name == "未命名")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean_rows(session)
        yield session
        session.rollback()
        _clean_rows(session)


def _payload(*, external_id: str = f"{CARD_PREFIX}structured") -> dict[str, object]:
    return {
        "cards": [
            {
                "id": external_id,
                "book": f"{BOOK_PREFIX} Book",
                "chapter": "第一章",
                "section": "第一节",
                "type": "definition",
                "question": "什么是阴阳？",
                "answer": "阴阳用于概括相互关联的对立属性。",
                "answer_points": ["相互关联", "对立属性"],
                "source_excerpt": "阴阳者，天地之道也。",
                "source_pages": [1, "2", True, "invalid"],
                "tags": ["基础理论", "阴阳"],
                "status": "approved",
                "confidence": 0.91,
            }
        ]
    }


def test_domain_services_keep_compatibility_import_structured_and_idempotent(
    db: Session,
) -> None:
    first = import_payload(db, _payload())
    second = import_payload(db, _payload())

    assert first.model_dump() == {
        "books_created": 1,
        "cards_upserted": 1,
        "review_states_created": 1,
        "skipped_non_approved": 0,
    }
    assert second.model_dump() == {
        "books_created": 0,
        "cards_upserted": 1,
        "review_states_created": 0,
        "skipped_non_approved": 0,
    }

    card = db.scalar(select(Card).where(Card.external_id == f"{CARD_PREFIX}structured"))
    assert card is not None
    assert card.answer_points == ["相互关联", "对立属性"]
    assert card.tags == ["基础理论", "阴阳"]
    assert card.answer_points_json is None
    assert card.tags_json is None
    assert db.scalar(select(func.count()).select_from(ReviewState)) == 1
    assert db.scalar(select(func.count()).select_from(CardReviewState)) == 0

    books = list_books(db)
    assert [(book.name, book.card_count) for book in books] == [(f"{BOOK_PREFIX} Book", 1)]
    cards = list_cards(db, q="阴阳")
    assert len(cards) == 1
    assert cards[0].answer_points == ["相互关联", "对立属性"]
    assert cards[0].tags == ["基础理论", "阴阳"]
    assert cards[0].source_pages == [1, 2]


def test_import_deduplicates_repeated_cards_in_one_payload(db: Session) -> None:
    payload = _payload(external_id=f"{CARD_PREFIX}repeated")
    cards = payload["cards"]
    assert isinstance(cards, list)
    cards.append(dict(cards[0]))

    result = import_payload(db, payload)

    assert result.cards_upserted == 2
    assert result.review_states_created == 1
    assert db.scalar(select(func.count()).select_from(Card)) == 1
    assert db.scalar(select(func.count()).select_from(ReviewState)) == 1


def test_import_uses_stable_id_for_cards_without_an_explicit_id(db: Session) -> None:
    payload = _payload(external_id="")
    cards = payload["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0].pop("id")
    first = import_payload(db, payload)
    second = import_payload(db, payload)

    assert first.cards_upserted == 1
    assert second.cards_upserted == 1
    assert second.books_created == 0
    assert second.review_states_created == 0
    assert db.scalar(select(func.count()).select_from(Card)) == 1


def test_legacy_adapter_keeps_state_for_non_approved_compatibility_import(db: Session) -> None:
    payload = _payload(external_id=f"{CARD_PREFIX}candidate")
    cards = payload["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["status"] = "candidate"
    result = import_payload(db, payload, only_approved=False)

    assert result.cards_upserted == 1
    assert result.review_states_created == 1
    card = db.scalar(select(Card).where(Card.external_id == f"{CARD_PREFIX}candidate"))
    assert card is not None and card.status == "candidate"
    assert db.scalar(select(CardReviewState.id).where(CardReviewState.card_id == card.id)) is None


def test_legacy_adapter_normalizes_explicit_null_defaults(db: Session) -> None:
    payload = _payload(external_id=f"{CARD_PREFIX}null-defaults")
    cards = payload["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0].update(
        {
            "book": None,
            "type": None,
            "status": None,
            "answer_points": None,
            "source_excerpt": None,
            "tags": None,
        }
    )

    result = import_payload(db, payload, only_approved=False)

    assert result.cards_upserted == 1
    card = db.scalar(select(Card).where(Card.external_id == f"{CARD_PREFIX}null-defaults"))
    assert card is not None
    assert card.book.name == "未命名"
    assert card.card_type == "other"
    assert card.status == "candidate"
    assert card.answer_points == []
    assert card.source_excerpt == ""
    assert card.tags == []


def test_catalog_output_reads_legacy_json_without_overriding_structured_values(
    db: Session,
) -> None:
    book = Book(name=f"{BOOK_PREFIX} Legacy", subject="测试")
    db.add(book)
    db.flush()
    card = Card(
        external_id=f"{CARD_PREFIX}legacy",
        book_id=book.id,
        card_type="definition",
        question="旧问题",
        answer="旧答案",
        answer_points_json='["旧要点"]',
        source_pages_json='[3, "4", false, "bad"]',
        tags_json='["旧标签"]',
        answer_points=[],
        tags=[],
        status="approved",
    )
    db.add(card)
    db.commit()

    legacy = card_to_out(card)
    assert legacy.answer_points == ["旧要点"]
    assert legacy.tags == ["旧标签"]
    assert legacy.source_pages == [3, 4]

    card.answer_points = ["结构化要点"]
    card.tags = ["结构化标签"]
    db.commit()
    structured = card_to_out(card)
    assert structured.answer_points == ["结构化要点"]
    assert structured.tags == ["结构化标签"]

    card.answer_points = []
    card.tags = []
    card.answer_points_json = "not-json"
    card.tags_json = '{"not": "a list"}'
    card.source_pages_json = "not-json"
    db.commit()
    malformed = card_to_out(card)
    assert malformed.answer_points == []
    assert malformed.tags == []
    assert malformed.source_pages == []


def test_legacy_learning_services_are_directly_callable(db: Session) -> None:
    import_payload(db, _payload(external_id=f"{CARD_PREFIX}learning"))
    card = db.scalar(select(Card).where(Card.external_id == f"{CARD_PREFIX}learning"))
    assert card is not None and card.review_state is not None
    card.review_state.due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    due = list_due(db, limit=5)
    assert [item.card.id for item in due] == [card.id]

    result = answer_review(db, card_id=card.id, rating=3)
    assert result.card_id == card.id
    assert result.rating == 3
    assert result.reps == 1
    assert db.scalar(select(func.count()).select_from(ReviewLog)) == 1

    summary = stats(db)
    assert summary.books == 1
    assert summary.cards_approved == 1
    assert summary.reviewed_today == 1


def test_import_rolls_back_the_whole_payload_on_database_failure(db: Session) -> None:
    payload = _payload(external_id=f"{CARD_PREFIX}rollback-first")
    cards = payload["cards"]
    assert isinstance(cards, list)
    cards.append(
        {
            "id": f"{CARD_PREFIX}rollback-invalid",
            "book": f"{BOOK_PREFIX} Rollback",
            "question": "会触发数据库类型错误吗？",
            "answer": "会。",
            "status": "approved",
            "confidence": {"not": "a float"},
        }
    )

    with pytest.raises(InvalidRequestError) as error:
        import_payload(db, payload)
    assert error.value.code == "INVALID_IMPORT_CARD"

    assert (
        db.scalar(
            select(func.count())
            .select_from(Card)
            .where(Card.external_id.like(f"{CARD_PREFIX}rollback-%"))
        )
        == 0
    )
    assert (
        db.scalar(select(func.count()).select_from(Book).where(Book.name.like(f"{BOOK_PREFIX}%")))
        == 0
    )


def test_answer_rolls_back_on_invalid_rating_and_session_remains_usable(
    db: Session,
) -> None:
    book = Book(name=f"{BOOK_PREFIX} Invalid Rating", subject="测试")
    db.add(book)
    db.flush()
    card = Card(
        external_id=f"{CARD_PREFIX}invalid-rating",
        book_id=book.id,
        card_type="definition",
        question="非法评分会怎样？",
        answer="整个写事务回滚。",
        source_excerpt="测试摘录",
        answer_points=[],
        tags=[],
        status="approved",
    )
    db.add(card)
    db.commit()
    assert db.scalar(select(ReviewState.id).where(ReviewState.card_id == card.id)) is None

    with pytest.raises(ValueError, match="rating must be 1..4"):
        answer_review(db, card_id=card.id, rating=99)

    assert db.scalar(select(func.count()).select_from(ReviewLog)) == 0
    state = db.scalar(select(ReviewState).where(ReviewState.card_id == card.id))
    assert state is None
