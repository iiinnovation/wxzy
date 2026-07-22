from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_token
from ..db import get_db
from ..schemas import ReviewAnswerIn, ReviewAnswerOut, ReviewDueItem
from ..services_cards import answer_review, list_due

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/due", response_model=list[ReviewDueItem])
def get_due(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    return list_due(db, limit=limit)


@router.post("/answer", response_model=ReviewAnswerOut)
def post_answer(
    body: ReviewAnswerIn,
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    return answer_review(db, card_id=body.card_id, rating=body.rating)
