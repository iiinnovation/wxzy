from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..learning.models import CardEnrollment, CardReviewState
from ..learning.services import is_mastered_state
from ..schemas import CardOut
from .models import Book, Card, CardSource, Chapter, DocumentChunk
from .schemas import (
    LearningBookOut,
    LearningCardDetailOut,
    LearningCardPageOut,
    LearningChapterOut,
)
from .services import card_to_out, list_card_source_contracts


class LearningCatalogReferenceError(RuntimeError):
    pass


def _mastered(state: CardReviewState | None, now: datetime) -> bool:
    return is_mastered_state(state, now=now)


def _owner_rows(
    db: Session, *, user_id: int
) -> tuple[dict[int, CardEnrollment], dict[int, CardReviewState]]:
    enrollments = {
        row.card_id: row
        for row in db.scalars(
            select(CardEnrollment).where(
                CardEnrollment.user_id == user_id,
                CardEnrollment.status != "retired",
            )
        )
    }
    states = {
        row.card_id: row
        for row in db.scalars(select(CardReviewState).where(CardReviewState.user_id == user_id))
    }
    return enrollments, states


def _published_chapter_tree(
    db: Session, *, book_id: int
) -> tuple[dict[int, Chapter], dict[int, set[int]]]:
    rows = db.execute(
        select(Chapter, Card.id)
        .join(DocumentChunk, DocumentChunk.chapter_id == Chapter.id)
        .join(CardSource, CardSource.document_chunk_id == DocumentChunk.id)
        .join(Card, Card.id == CardSource.card_id)
        .where(Card.book_id == book_id, Card.status == "published")
        .order_by(Chapter.sort_order, Chapter.id, Card.id)
    ).all()
    chapters = {chapter.id: chapter for chapter, _card_id in rows}
    direct_cards: dict[int, set[int]] = {}
    for chapter, card_id in rows:
        direct_cards.setdefault(chapter.id, set()).add(card_id)

    pending_parent_ids = {
        chapter.parent_id
        for chapter in chapters.values()
        if chapter.parent_id is not None and chapter.parent_id not in chapters
    }
    while pending_parent_ids:
        parents = list(db.scalars(select(Chapter).where(Chapter.id.in_(pending_parent_ids))))
        if not parents:
            break
        pending_parent_ids = set()
        for parent in parents:
            chapters[parent.id] = parent
            if parent.parent_id is not None and parent.parent_id not in chapters:
                pending_parent_ids.add(parent.parent_id)

    subtree_cards = {chapter_id: set(card_ids) for chapter_id, card_ids in direct_cards.items()}
    for chapter_id, card_ids in direct_cards.items():
        parent_id = chapters[chapter_id].parent_id
        visited = {chapter_id}
        while parent_id is not None and parent_id in chapters and parent_id not in visited:
            subtree_cards.setdefault(parent_id, set()).update(card_ids)
            visited.add(parent_id)
            parent_id = chapters[parent_id].parent_id
    return chapters, subtree_cards


def _chapter_subtree_ids(db: Session, *, chapter_id: int) -> list[int]:
    root = db.get(Chapter, chapter_id)
    if root is None:
        return []
    children_by_parent: dict[int | None, list[int]] = {}
    for row in db.scalars(
        select(Chapter).where(Chapter.document_version_id == root.document_version_id)
    ):
        children_by_parent.setdefault(row.parent_id, []).append(row.id)
    result: list[int] = []
    pending = [root.id]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        result.append(current)
        pending.extend(children_by_parent.get(current, []))
    return result


def list_learning_books(db: Session, *, user_id: int) -> list[LearningBookOut]:
    now = datetime.now(UTC)
    enrollments, states = _owner_rows(db, user_id=user_id)
    result: list[LearningBookOut] = []
    for book in db.scalars(select(Book).order_by(Book.id)):
        card_ids = set(
            db.scalars(select(Card.id).where(Card.book_id == book.id, Card.status == "published"))
        )
        chapters, _chapter_cards = _published_chapter_tree(db, book_id=book.id)
        enrolled_ids = card_ids & set(enrollments)
        active_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "active"
        }
        queued_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "queued"
        }
        suspended_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "suspended"
        }
        result.append(
            LearningBookOut(
                id=book.id,
                name=book.name,
                subject=book.subject,
                chapter_count=len(chapters),
                published_card_count=len(card_ids),
                enrolled_card_count=len(enrolled_ids),
                queued_card_count=len(queued_ids),
                active_card_count=len(active_ids),
                suspended_card_count=len(suspended_ids),
                mastered_card_count=sum(
                    _mastered(states.get(card_id), now) for card_id in active_ids
                ),
            )
        )
    return result


def list_learning_chapters(db: Session, *, user_id: int, book_id: int) -> list[LearningChapterOut]:
    if db.get(Book, book_id) is None:
        raise LearningCatalogReferenceError("book does not exist")
    now = datetime.now(UTC)
    enrollments, states = _owner_rows(db, user_id=user_id)
    chapters, card_ids_by_chapter = _published_chapter_tree(db, book_id=book_id)
    result: list[LearningChapterOut] = []
    for chapter in sorted(chapters.values(), key=lambda row: (row.sort_order, row.id)):
        card_ids = card_ids_by_chapter.get(chapter.id, set())
        enrolled_ids = card_ids & set(enrollments)
        active_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "active"
        }
        queued_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "queued"
        }
        suspended_ids = {
            card_id for card_id in enrolled_ids if enrollments[card_id].status == "suspended"
        }
        result.append(
            LearningChapterOut(
                id=chapter.id,
                parent_id=chapter.parent_id,
                title=chapter.title,
                level=chapter.level,
                sort_order=chapter.sort_order,
                pdf_page_start=chapter.pdf_page_index_start + 1,
                pdf_page_end=chapter.pdf_page_index_end + 1,
                published_card_count=len(card_ids),
                enrolled_card_count=len(enrolled_ids),
                queued_card_count=len(queued_ids),
                active_card_count=len(active_ids),
                suspended_card_count=len(suspended_ids),
                mastered_card_count=sum(
                    _mastered(states.get(card_id), now) for card_id in active_ids
                ),
            )
        )
    return result


def get_learning_card(db: Session, *, user_id: int, card_id: int) -> LearningCardDetailOut:
    card = db.scalar(
        select(Card)
        .options(joinedload(Card.book), selectinload(Card.sources))
        .where(Card.id == card_id, Card.status == "published")
        .limit(1)
    )
    if card is None:
        raise LearningCatalogReferenceError("card does not exist")
    enrollment = db.scalar(
        select(CardEnrollment).where(
            CardEnrollment.user_id == user_id,
            CardEnrollment.card_id == card_id,
            CardEnrollment.status != "retired",
        )
    )
    state = db.scalar(
        select(CardReviewState).where(
            CardReviewState.user_id == user_id,
            CardReviewState.card_id == card_id,
        )
    )
    return LearningCardDetailOut(
        card=card_to_out(card),
        sources=list_card_source_contracts(db, card_id=card_id),
        enrollment_id=enrollment.id if enrollment else None,
        enrollment_status=enrollment.status if enrollment else None,
        review_state=state.state if state else None,
        mastered=_mastered(state, datetime.now(UTC)),
    )


def search_learning_cards(
    db: Session,
    *,
    book_id: int | None,
    chapter_id: int | None,
    query: str | None,
    offset: int,
    limit: int,
) -> LearningCardPageOut:
    statement = select(Card).options(joinedload(Card.book), selectinload(Card.sources)).join(Book)
    count_statement = select(func.count(func.distinct(Card.id))).select_from(Card).join(Book)
    if chapter_id is not None:
        chapter_ids = _chapter_subtree_ids(db, chapter_id=chapter_id)
        statement = (
            statement.join(CardSource)
            .join(DocumentChunk)
            .where(DocumentChunk.chapter_id.in_(chapter_ids))
        )
        count_statement = (
            count_statement.join(CardSource)
            .join(DocumentChunk)
            .where(DocumentChunk.chapter_id.in_(chapter_ids))
        )
    filters = [Card.status == "published"]
    if book_id is not None:
        filters.append(Card.book_id == book_id)
    if query:
        like = f"%{query.strip()}%"
        filters.append(
            or_(
                Card.question.ilike(like),
                Card.answer.ilike(like),
                Card.chapter.ilike(like),
                Card.section.ilike(like),
                Book.name.ilike(like),
                cast(Card.tags, String).ilike(like),
            )
        )
    statement = statement.where(*filters).distinct().order_by(Card.id).offset(offset).limit(limit)
    count_statement = count_statement.where(*filters)
    total = int(db.scalar(count_statement) or 0)
    items: list[CardOut] = [card_to_out(card) for card in db.scalars(statement).unique()]
    return LearningCardPageOut(
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
        items=items,
    )
