from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.daily_plan import (
    DailyPlanReferenceError,
    DailyPlanStateError,
    adjust_today_budget,
    get_or_create_today_plan,
)
from ...learning.schemas import DailyPlanBudgetAdjust, DailyPlanOut

router = APIRouter(tags=["learning"])


@router.get("/learning/today", response_model=DailyPlanOut)
def get_learning_today(
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> DailyPlanOut:
    try:
        plan = get_or_create_today_plan(db, user_id=owner.id)
    except DailyPlanReferenceError as exc:
        raise ResourceNotFoundError(
            code="DAILY_PLAN_OWNER_NOT_FOUND",
            message=str(exc),
        ) from exc
    except DailyPlanStateError as exc:
        raise InvalidRequestError(code="DAILY_PLAN_INVALID", message=str(exc)) from exc
    return DailyPlanOut.from_plan(plan)


# PUT alias: wx.request does not support the PATCH method on real devices.
@router.patch("/learning/today", response_model=DailyPlanOut)
@router.put("/learning/today", response_model=DailyPlanOut)
def patch_learning_today(
    body: DailyPlanBudgetAdjust,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> DailyPlanOut:
    try:
        plan = adjust_today_budget(
            db,
            user_id=owner.id,
            budget_minutes=body.budget_minutes,
        )
    except DailyPlanReferenceError as exc:
        raise ResourceNotFoundError(
            code="DAILY_PLAN_OWNER_NOT_FOUND",
            message=str(exc),
        ) from exc
    except DailyPlanStateError as exc:
        raise InvalidRequestError(code="DAILY_PLAN_INVALID", message=str(exc)) from exc
    return DailyPlanOut.from_plan(plan)
