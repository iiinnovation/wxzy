"""P5-T10: import first formal publication and verify catalog visibility."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from tools.document_pipeline.first_publication import (
    BOOK_SPECS,
    PUBLICATION_ID,
    build_first_publication,
    verify_imported_first_publication,
)

from app.catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.catalog.services import CATALOG_VISIBLE_STATUSES, list_books, list_cards
from app.db import engine
from app.learning.models import CardEnrollment, CardReviewState
from app.learning.services import list_due
from app.models import ReviewLog, ReviewState
from app.publishing.models import PublicationImport

PREFIX_BOOKS = {spec["book"] for spec in BOOK_SPECS}
PUBLICATION_ID_TEST = f"{PUBLICATION_ID}-test"


def _clean(db: Session) -> None:
    card_ids = list(
        db.scalars(
            select(Card.id).where(
                (Card.external_id.like("%-d7d8e93f8e"))  # noop wide net avoided
                | (Card.book_id.in_(select(Book.id).where(Book.name.in_(PREFIX_BOOKS))))
            )
        ).all()
    )
    # broader cleanup by book names used in first batch
    book_ids = list(db.scalars(select(Book.id).where(Book.name.in_(PREFIX_BOOKS))).all())
    if book_ids:
        more = list(db.scalars(select(Card.id).where(Card.book_id.in_(book_ids))).all())
        card_ids = sorted(set(card_ids + more))
    if card_ids:
        db.execute(delete(CardSource).where(CardSource.card_id.in_(card_ids)))
        db.execute(delete(ReviewLog).where(ReviewLog.card_id.in_(card_ids)))
        db.execute(delete(ReviewState).where(ReviewState.card_id.in_(card_ids)))
        db.execute(delete(CardReviewState).where(CardReviewState.card_id.in_(card_ids)))
        db.execute(delete(CardEnrollment).where(CardEnrollment.card_id.in_(card_ids)))
        db.execute(delete(Card).where(Card.id.in_(card_ids)))
    db.execute(delete(PublicationImport).where(PublicationImport.publication_id.like("pub-first-batch%")))
    # clean docs/chapters/chunks created by import for these document keys
    doc_keys = [spec["key"] for spec in BOOK_SPECS]
    docs = list(db.scalars(select(Document).where(Document.document_key.in_(doc_keys))).all())
    doc_ids = [d.id for d in docs]
    if doc_ids:
        versions = list(
            db.scalars(select(DocumentVersion).where(DocumentVersion.document_id.in_(doc_ids))).all()
        )
        version_ids = [v.id for v in versions]
        if version_ids:
            chunks = list(
                db.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_version_id.in_(version_ids))
                ).all()
            )
            chunk_ids = [c.id for c in chunks]
            if chunk_ids:
                db.execute(delete(CardSource).where(CardSource.document_chunk_id.in_(chunk_ids)))
                db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
            db.execute(delete(Chapter).where(Chapter.document_version_id.in_(version_ids)))
            db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))
        db.execute(delete(Document).where(Document.id.in_(doc_ids)))
    db.execute(delete(Book).where(Book.name.in_(PREFIX_BOOKS)))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean(session)
        yield session
        session.rollback()
        _clean(session)


def test_catalog_lists_published_cards_by_default(db: Session) -> None:
    book = Book(name="中医基础理论", subject="基础理论")
    db.add(book)
    db.flush()
    approved = Card(
        external_id="catalog-visible-approved",
        book_id=book.id,
        card_type="concept_definition",
        question="approved q",
        answer="approved a",
        source_excerpt="src",
        status="approved",
    )
    published = Card(
        external_id="catalog-visible-published",
        book_id=book.id,
        card_type="concept_definition",
        question="published q",
        answer="published a",
        source_excerpt="src",
        status="published",
    )
    hidden = Card(
        external_id="catalog-visible-candidate",
        book_id=book.id,
        card_type="concept_definition",
        question="candidate q",
        answer="candidate a",
        source_excerpt="src",
        status="candidate",
    )
    db.add_all([approved, published, hidden])
    db.commit()

    books = list_books(db)
    hit = next(b for b in books if b.name == "中医基础理论")
    assert hit.card_count == 2

    default_cards = list_cards(db, book_id=book.id)
    statuses = {c.status for c in default_cards}
    assert statuses == set(CATALOG_VISIBLE_STATUSES)
    assert "candidate" not in statuses

    approved_only = list_cards(db, book_id=book.id, status="approved")
    assert [c.external_id for c in approved_only] == ["catalog-visible-approved"]


def test_first_publication_import_acceptance(db: Session, tmp_path: Path) -> None:
    built = build_first_publication(
        out_dir=tmp_path / "first-pub",
        publication_id=PUBLICATION_ID_TEST,
        reviewer="p5t10-tester",
    )
    assert len(built.book_summaries) == 7
    assert built.source_coverage == 1.0
    assert built.high_risk_review_coverage == 1.0

    check = verify_imported_first_publication(
        db,
        package_dir=built.package.out_dir,
        expected_books=[spec["book"] for spec in BOOK_SPECS],
        expected_card_ids=[c.id for c in built.cards],
        high_risk_cards=[
            c
            for c in built.cards
            if (c.risk_level.value if hasattr(c.risk_level, "value") else str(c.risk_level))
            in {"high", "critical"}
        ],
    )
    assert check.ok is True, check.to_dict()
    assert check.books_visible == 7
    assert check.published_cards == len(built.cards)
    assert check.source_coverage == 1.0
    assert check.high_risk_review_coverage == 1.0
    assert check.due_after == check.due_before == 0
    assert check.review_states_created == 0
    assert check.card_review_states_created == 0
    assert check.idempotent_replay is True

    books = list_books(db)
    visible = {b.name: b.card_count for b in books if b.name in PREFIX_BOOKS}
    assert set(visible) == PREFIX_BOOKS
    assert all(count > 0 for count in visible.values())

    cards = list_cards(db, limit=200)
    batch_cards = [c for c in cards if c.external_id in {x.id for x in built.cards}]
    assert len(batch_cards) == len(built.cards)
    assert all(c.status == "published" for c in batch_cards)
    # every published card has >=1 CardSource
    for card in batch_cards:
        n = int(
            db.scalar(select(func.count()).select_from(CardSource).where(CardSource.card_id == card.id))
            or 0
        )
        assert n >= 1, card.external_id
    assert len(list_due(db, limit=100)) == 0
