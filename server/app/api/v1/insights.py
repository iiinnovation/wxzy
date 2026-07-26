from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.insights import (
    InsightReferenceError,
    InsightStateError,
    build_insight_summary,
    build_insight_workload,
    build_weak_topic_page,
)
from ...learning.schemas import (
    InsightSummaryOut,
    InsightWeakTopicPageOut,
    InsightWorkloadOut,
)

router = APIRouter(tags=["insights"])


def _raise_insight_error(exc: Exception) -> NoReturn:
    if isinstance(exc, InsightReferenceError):
        raise ResourceNotFoundError(
            code="INSIGHT_OWNER_NOT_FOUND",
            message=str(exc),
        ) from exc
    raise InvalidRequestError(code="INSIGHT_INVALID", message=str(exc)) from exc


@router.get("/insights/summary", response_model=InsightSummaryOut)
def get_insight_summary(
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> InsightSummaryOut:
    try:
        return build_insight_summary(db, user_id=owner.id)
    except (InsightReferenceError, InsightStateError) as exc:
        _raise_insight_error(exc)


@router.get("/insights/workload", response_model=InsightWorkloadOut)
def get_insight_workload(
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> InsightWorkloadOut:
    try:
        return build_insight_workload(db, user_id=owner.id)
    except (InsightReferenceError, InsightStateError) as exc:
        _raise_insight_error(exc)


@router.get("/insights/weak-topics", response_model=InsightWeakTopicPageOut)
def get_insight_weak_topics(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> InsightWeakTopicPageOut:
    try:
        return build_weak_topic_page(
            db,
            user_id=owner.id,
            offset=offset,
            limit=limit,
        )
    except (InsightReferenceError, InsightStateError) as exc:
        _raise_insight_error(exc)
