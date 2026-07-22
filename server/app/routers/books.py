from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_token
from ..db import get_db
from ..schemas import BookOut
from ..services_cards import list_books

router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=list[BookOut])
def get_books(
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    return list_books(db)
