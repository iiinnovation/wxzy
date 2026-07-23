from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_token
from ..catalog.services import list_cards
from ..db import get_db
from ..schemas import CardOut

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=list[CardOut])
def get_cards(
    book_id: int | None = None,
    status: str = "approved",
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    return list_cards(db, book_id=book_id, status=status, q=q, limit=limit, offset=offset)
