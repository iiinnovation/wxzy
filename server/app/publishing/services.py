from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catalog.models import Book, Card
from ..config import get_settings
from ..core.errors import InvalidRequestError
from ..fsrs_simple import utcnow
from ..models import ReviewState
from ..schemas import ImportResult
from .schemas import CompatibilityCardImport


def _stable_external_id(card: CompatibilityCardImport) -> str:
    if card.external_id:
        return card.external_id
    fingerprint = json.dumps(
        {
            "book": card.book_name,
            "chapter": card.chapter,
            "section": card.section,
            "question": card.question,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return f"gen-{hashlib.sha1(fingerprint).hexdigest()[:16]}"


def import_payload(
    db: Session, payload: dict[str, Any], *, only_approved: bool = True
) -> ImportResult:
    cards_in = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards_in, list):
        raise InvalidRequestError(
            code="INVALID_IMPORT_PAYLOAD",
            message="卡片导入数据格式无效",
        )

    books_created = 0
    cards_upserted = 0
    review_created = 0
    skipped = 0
    book_cache: dict[str, Book] = {}

    try:
        for index, raw in enumerate(cards_in):
            if not isinstance(raw, dict):
                continue
            status = str(raw.get("status") or "candidate").strip() or "candidate"
            if only_approved and status != "approved":
                skipped += 1
                continue

            question = str(raw.get("question") or "").strip()
            answer = str(raw.get("answer") or "").strip()
            if not question or not answer:
                skipped += 1
                continue

            try:
                values = CompatibilityCardImport.model_validate(raw)
            except ValidationError as exc:
                raise InvalidRequestError(
                    code="INVALID_IMPORT_CARD",
                    message="卡片导入字段无效",
                    details={"card_index": index},
                ) from exc

            book_name = values.book_name
            if book_name not in book_cache:
                book = db.scalar(select(Book).where(Book.name == book_name))
                if book is None:
                    book = Book(name=book_name, subject=None)
                    db.add(book)
                    db.flush()
                    books_created += 1
                book_cache[book_name] = book
            book = book_cache[book_name]

            external_id = _stable_external_id(values)
            card = db.scalar(select(Card).where(Card.external_id == external_id))
            if card is None:
                card = Card(external_id=external_id, book_id=book.id)
                db.add(card)

            card.book_id = book.id
            card.chapter = values.chapter
            card.section = values.section
            card.card_type = values.card_type
            card.question = values.question
            card.answer = values.answer
            card.answer_points = list(values.answer_points)
            card.answer_points_json = None
            card.source_excerpt = values.source_excerpt
            # Candidate v1 has no chunk identity. Keep source pages in the read-only
            # compatibility column until P5 publishes them as CardSource rows.
            card.source_pages_json = json.dumps(values.source_pages, ensure_ascii=False)
            card.tags = list(values.tags)
            card.tags_json = None
            card.status = "approved" if only_approved else values.status
            card.confidence = values.confidence
            db.flush()

            # This is deliberately the legacy state used by the compatibility API. It
            # never creates the user-scoped CardReviewState used by the target domain.
            # Keep the old adapter's behavior for ``only_approved=False`` as well; the
            # legacy due query still excludes non-approved cards.
            legacy_state = db.scalar(
                select(ReviewState).where(ReviewState.card_id == card.id).limit(1)
            )
            if legacy_state is None:
                db.add(
                    ReviewState(
                        card_id=card.id,
                        due_at=utcnow(),
                        algorithm_version=get_settings().algorithm_version,
                    )
                )
                review_created += 1
            cards_upserted += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ImportResult(
        books_created=books_created,
        cards_upserted=cards_upserted,
        review_states_created=review_created,
        skipped_non_approved=skipped,
    )
