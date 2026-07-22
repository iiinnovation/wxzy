from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .fsrs_simple import schedule, utcnow
from .schemas import CardOut, ImportResult, ReviewAnswerOut, ReviewDueItem, StatsOut


def _loads_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except json.JSONDecodeError:
        return []


def card_to_out(card: models.Card) -> CardOut:
    return CardOut(
        id=card.id,
        external_id=card.external_id,
        book_id=card.book_id,
        book_name=card.book.name if card.book else None,
        chapter=card.chapter,
        section=card.section,
        card_type=card.card_type,
        question=card.question,
        answer=card.answer,
        answer_points=_loads_list(card.answer_points_json),
        source_excerpt=card.source_excerpt or "",
        source_pages=[int(x) for x in _loads_list(card.source_pages_json) if str(x).isdigit() or isinstance(x, int)],
        tags=[str(x) for x in _loads_list(card.tags_json)],
        status=card.status,
        confidence=card.confidence,
    )


def list_books(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(models.Book, func.count(models.Card.id))
        .outerjoin(models.Card, (models.Card.book_id == models.Book.id) & (models.Card.status == "approved"))
        .group_by(models.Book.id)
        .order_by(models.Book.id)
    ).all()
    return [
        {"id": b.id, "name": b.name, "subject": b.subject, "card_count": int(cnt or 0)}
        for b, cnt in rows
    ]


def list_cards(
    db: Session,
    *,
    book_id: int | None = None,
    status: str = "approved",
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CardOut]:
    stmt = select(models.Card).join(models.Book).where(models.Card.status == status)
    if book_id is not None:
        stmt = stmt.where(models.Card.book_id == book_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (models.Card.question.ilike(like))
            | (models.Card.answer.ilike(like))
            | (models.Card.section.ilike(like))
        )
    stmt = stmt.order_by(models.Card.id).offset(offset).limit(min(limit, 200))
    cards = db.scalars(stmt).all()
    return [card_to_out(c) for c in cards]


def ensure_review_state(db: Session, card: models.Card) -> models.ReviewState:
    if card.review_state:
        return card.review_state
    rs = models.ReviewState(
        card_id=card.id,
        due_at=utcnow(),
        stability=1.0,
        difficulty=5.0,
        state="new",
        algorithm_version=get_settings().algorithm_version,
    )
    db.add(rs)
    db.flush()
    return rs


def list_due(db: Session, *, limit: int = 30) -> list[ReviewDueItem]:
    now = utcnow()
    stmt = (
        select(models.ReviewState)
        .join(models.Card)
        .where(models.Card.status == "approved", models.ReviewState.due_at <= now)
        .order_by(models.ReviewState.due_at.asc())
        .limit(min(limit, 100))
    )
    states = db.scalars(stmt).all()
    items: list[ReviewDueItem] = []
    for st in states:
        items.append(
            ReviewDueItem(
                card=card_to_out(st.card),
                due_at=st.due_at,
                state=st.state,
                reps=st.reps,
                lapses=st.lapses,
                stability=st.stability,
                difficulty=st.difficulty,
            )
        )
    return items


def answer_review(db: Session, *, card_id: int, rating: int) -> ReviewAnswerOut:
    card = db.get(models.Card, card_id)
    if card is None or card.status != "approved":
        raise ValueError("card not found or not approved")
    st = ensure_review_state(db, card)
    before_due = st.due_at
    before_state = st.state
    result = schedule(
        rating=rating,
        stability=st.stability,
        difficulty=st.difficulty,
        reps=st.reps,
        lapses=st.lapses,
        state=st.state,
        last_reviewed_at=st.last_reviewed_at,
    )
    st.due_at = result.due_at
    st.stability = result.stability
    st.difficulty = result.difficulty
    st.elapsed_days = result.elapsed_days
    st.scheduled_days = result.scheduled_days
    st.reps = result.reps
    st.lapses = result.lapses
    st.state = result.state
    st.last_rating = rating
    st.last_reviewed_at = utcnow()
    st.algorithm_version = get_settings().algorithm_version

    log = models.ReviewLog(
        card_id=card.id,
        rating=rating,
        due_before=before_due,
        due_after=result.due_at,
        stability_after=result.stability,
        difficulty_after=result.difficulty,
        algorithm_version=st.algorithm_version,
        state_before=before_state,
        state_after=result.state,
    )
    db.add(log)
    db.commit()
    db.refresh(st)
    return ReviewAnswerOut(
        card_id=card.id,
        rating=rating,
        due_at=st.due_at,
        scheduled_days=st.scheduled_days,
        stability=st.stability,
        difficulty=st.difficulty,
        state=st.state,
        reps=st.reps,
        lapses=st.lapses,
        algorithm_version=st.algorithm_version,
    )


def import_payload(db: Session, payload: dict[str, Any], *, only_approved: bool = True) -> ImportResult:
    cards_in = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards_in, list):
        raise ValueError("payload.cards must be a list")

    books_created = 0
    cards_upserted = 0
    review_created = 0
    skipped = 0
    book_cache: dict[str, models.Book] = {}

    for raw in cards_in:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "candidate")
        if only_approved and status != "approved":
            # allow candidate seed if explicitly approved already; otherwise skip
            skipped += 1
            continue
        book_name = str(raw.get("book") or "未命名").strip() or "未命名"
        if book_name not in book_cache:
            book = db.scalar(select(models.Book).where(models.Book.name == book_name))
            if book is None:
                book = models.Book(name=book_name, subject=None)
                db.add(book)
                db.flush()
                books_created += 1
            book_cache[book_name] = book
        book = book_cache[book_name]

        external_id = str(raw.get("id") or "").strip()
        if not external_id:
            # Python's built-in hash is randomized between processes; use a stable
            # digest so importing the same id-less card remains idempotent.
            fingerprint = json.dumps(
                {
                    "book": book_name,
                    "chapter": raw.get("chapter"),
                    "section": raw.get("section"),
                    "question": raw.get("question", ""),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            external_id = f"gen-{hashlib.sha1(fingerprint).hexdigest()[:16]}"

        card = db.scalar(select(models.Card).where(models.Card.external_id == external_id))
        points = raw.get("answer_points") or []
        pages = raw.get("source_pages") or []
        tags = raw.get("tags") or []
        fields = dict(
            book_id=book.id,
            chapter=raw.get("chapter"),
            section=raw.get("section"),
            card_type=str(raw.get("type") or "other"),
            question=str(raw.get("question") or "").strip(),
            answer=str(raw.get("answer") or "").strip(),
            answer_points_json=json.dumps(points, ensure_ascii=False),
            source_excerpt=str(raw.get("source_excerpt") or ""),
            source_pages_json=json.dumps(pages, ensure_ascii=False),
            tags_json=json.dumps(tags, ensure_ascii=False),
            status="approved" if only_approved else status,
            confidence=raw.get("confidence"),
        )
        if not fields["question"] or not fields["answer"]:
            skipped += 1
            continue
        if card is None:
            card = models.Card(external_id=external_id, **fields)
            db.add(card)
            db.flush()
            rs = models.ReviewState(
                card_id=card.id,
                due_at=utcnow(),
                algorithm_version=get_settings().algorithm_version,
            )
            db.add(rs)
            review_created += 1
        else:
            for k, v in fields.items():
                setattr(card, k, v)
            if card.review_state is None:
                db.add(
                    models.ReviewState(
                        card_id=card.id,
                        due_at=utcnow(),
                        algorithm_version=get_settings().algorithm_version,
                    )
                )
                review_created += 1
        cards_upserted += 1

    db.commit()
    return ImportResult(
        books_created=books_created,
        cards_upserted=cards_upserted,
        review_states_created=review_created,
        skipped_non_approved=skipped,
    )


def stats(db: Session) -> StatsOut:
    now = utcnow()
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    books = db.scalar(select(func.count()).select_from(models.Book)) or 0
    approved = db.scalar(select(func.count()).select_from(models.Card).where(models.Card.status == "approved")) or 0
    due = db.scalar(
        select(func.count())
        .select_from(models.ReviewState)
        .join(models.Card)
        .where(models.Card.status == "approved", models.ReviewState.due_at <= now)
    ) or 0
    reviewed_today = db.scalar(
        select(func.count()).select_from(models.ReviewLog).where(models.ReviewLog.reviewed_at >= start)
    ) or 0
    new_cards = db.scalar(
        select(func.count())
        .select_from(models.ReviewState)
        .join(models.Card)
        .where(models.Card.status == "approved", models.ReviewState.state == "new")
    ) or 0
    return StatsOut(
        books=int(books),
        cards_approved=int(approved),
        due_now=int(due),
        reviewed_today=int(reviewed_today),
        new_cards=int(new_cards),
    )
