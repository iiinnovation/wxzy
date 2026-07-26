from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...core.errors import ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.coach import RepairSuggestionReferenceError, build_repair_suggestions
from ...learning.schemas import RepairSuggestionListOut

router = APIRouter(tags=["learning"])


@router.get("/learning/repair-suggestions", response_model=RepairSuggestionListOut)
def get_learning_repair_suggestions(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> RepairSuggestionListOut:
    try:
        return build_repair_suggestions(db, user_id=owner.id, limit=limit)
    except RepairSuggestionReferenceError as exc:
        raise ResourceNotFoundError(
            code="REPAIR_SUGGESTION_OWNER_NOT_FOUND",
            message=str(exc),
        ) from exc
