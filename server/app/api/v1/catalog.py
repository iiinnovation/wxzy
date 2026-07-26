from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...catalog.read_models import (
    LearningCatalogReferenceError,
    get_learning_card,
    list_learning_books,
    list_learning_chapters,
    search_learning_cards,
)
from ...catalog.schemas import (
    CardSourceOut,
    LearningBookOut,
    LearningCardDetailOut,
    LearningCardPageOut,
    LearningChapterOut,
)
from ...core.errors import ResourceNotFoundError
from ...db import get_db
from ...identity.models import User

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/books", response_model=list[LearningBookOut])
def get_catalog_books(
    db: Session = Depends(get_db), owner: User = Depends(require_owner)
) -> list[LearningBookOut]:
    return list_learning_books(db, user_id=owner.id)


@router.get("/books/{book_id}/chapters", response_model=list[LearningChapterOut])
def get_catalog_chapters(
    book_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> list[LearningChapterOut]:
    try:
        return list_learning_chapters(db, user_id=owner.id, book_id=book_id)
    except LearningCatalogReferenceError as exc:
        raise ResourceNotFoundError(code="CATALOG_BOOK_NOT_FOUND", message=str(exc)) from exc


@router.get("/cards", response_model=LearningCardPageOut)
def get_catalog_cards(
    book_id: int | None = None,
    chapter_id: int | None = None,
    q: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _owner: User = Depends(require_owner),
) -> LearningCardPageOut:
    return search_learning_cards(
        db,
        book_id=book_id,
        chapter_id=chapter_id,
        query=q,
        offset=offset,
        limit=limit,
    )


@router.get("/cards/{card_id}", response_model=LearningCardDetailOut)
def get_catalog_card(
    card_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> LearningCardDetailOut:
    try:
        return get_learning_card(db, user_id=owner.id, card_id=card_id)
    except LearningCatalogReferenceError as exc:
        raise ResourceNotFoundError(code="CATALOG_CARD_NOT_FOUND", message=str(exc)) from exc


@router.get("/cards/{card_id}/sources", response_model=list[CardSourceOut])
def get_catalog_card_sources(
    card_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
):
    return get_catalog_card(card_id=card_id, db=db, owner=owner).sources
