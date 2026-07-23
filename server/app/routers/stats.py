from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_token
from ..db import get_db
from ..learning.services import stats
from ..schemas import StatsOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=StatsOut)
def get_summary(
    db: Session = Depends(get_db),
    _token: str = Depends(require_token),
):
    return stats(db)
