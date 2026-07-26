from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...catalog.services import card_to_out
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.schemas import (
    DailyPlanItemOut,
    ReviewAttemptOut,
    ReviewAttemptRequest,
    StudySessionCreate,
    StudySessionInterruptRequest,
    StudySessionNextOut,
    StudySessionOut,
    StudySessionRequest,
    StudySessionTaskOut,
)
from ...learning.services import (
    ReviewAttemptConflictError,
    ReviewAttemptReferenceError,
    StudySessionReferenceError,
    StudySessionStateError,
    complete_plan_study_session,
    create_plan_study_session,
    create_study_session,
    get_next_study_task,
    interrupt_plan_study_session,
    resume_plan_study_session,
    start_study_session,
    submit_review_attempt,
)

router = APIRouter(tags=["learning"])


@router.post("/study-sessions", response_model=StudySessionOut)
def post_study_session(
    body: StudySessionRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> StudySessionOut:
    try:
        if body.daily_plan_id is not None:
            session = create_plan_study_session(
                db,
                user_id=owner.id,
                daily_plan_id=body.daily_plan_id,
                auto_start=body.auto_start,
            )
        else:
            session = create_study_session(
                db,
                StudySessionCreate(
                    user_id=owner.id,
                    session_type=body.session_type,
                    estimated_minutes=body.estimated_minutes,
                    planned_task_count=body.planned_task_count,
                ),
            )
            if body.auto_start:
                session = start_study_session(db, session_id=session.id)
    except StudySessionReferenceError as exc:
        raise ResourceNotFoundError(
            code="STUDY_SESSION_OWNER_NOT_FOUND",
            message=str(exc),
        ) from exc
    except StudySessionStateError as exc:
        raise InvalidRequestError(
            code="STUDY_SESSION_STATE_INVALID",
            message=str(exc),
            status_code=409,
        ) from exc
    return StudySessionOut.model_validate(session, from_attributes=True)


def _raise_study_session_error(exc: Exception) -> None:
    if isinstance(exc, StudySessionReferenceError):
        raise ResourceNotFoundError(
            code="STUDY_SESSION_NOT_FOUND",
            message=str(exc),
        ) from exc
    raise InvalidRequestError(
        code="STUDY_SESSION_STATE_INVALID",
        message=str(exc),
        status_code=409,
    ) from exc


@router.get("/study-sessions/{session_id}/next", response_model=StudySessionNextOut)
def get_study_session_next(
    session_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> StudySessionNextOut:
    try:
        result = get_next_study_task(db, session_id=session_id, user_id=owner.id)
    except (StudySessionReferenceError, StudySessionStateError) as exc:
        _raise_study_session_error(exc)
    task = None
    if result.plan_item is not None:
        assert result.card is not None and result.review_state is not None
        task = StudySessionTaskOut(
            plan_item=DailyPlanItemOut.model_validate(result.plan_item, from_attributes=True),
            card=card_to_out(result.card),
            card_revision=result.card.content_revision,
            review_state=result.review_state,
        )
    return StudySessionNextOut(
        session=StudySessionOut.model_validate(result.session, from_attributes=True),
        task=task,
    )


@router.post("/study-sessions/{session_id}/complete", response_model=StudySessionOut)
def post_study_session_complete(
    session_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> StudySessionOut:
    try:
        session = complete_plan_study_session(db, session_id=session_id, user_id=owner.id)
    except (StudySessionReferenceError, StudySessionStateError) as exc:
        _raise_study_session_error(exc)
    return StudySessionOut.model_validate(session, from_attributes=True)


@router.post("/study-sessions/{session_id}/interrupt", response_model=StudySessionOut)
def post_study_session_interrupt(
    session_id: int,
    body: StudySessionInterruptRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> StudySessionOut:
    try:
        session = interrupt_plan_study_session(
            db,
            session_id=session_id,
            user_id=owner.id,
            reason=body.reason,
        )
    except (StudySessionReferenceError, StudySessionStateError) as exc:
        _raise_study_session_error(exc)
    return StudySessionOut.model_validate(session, from_attributes=True)


@router.post("/study-sessions/{session_id}/resume", response_model=StudySessionOut)
def post_study_session_resume(
    session_id: int,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> StudySessionOut:
    try:
        session = resume_plan_study_session(db, session_id=session_id, user_id=owner.id)
    except (StudySessionReferenceError, StudySessionStateError) as exc:
        _raise_study_session_error(exc)
    return StudySessionOut.model_validate(session, from_attributes=True)


@router.post("/review-attempts", response_model=ReviewAttemptOut)
def post_review_attempt(
    body: ReviewAttemptRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> ReviewAttemptOut:
    try:
        result = submit_review_attempt(db, body.to_create(user_id=owner.id))
    except ReviewAttemptReferenceError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise ResourceNotFoundError(
                code="REVIEW_ATTEMPT_NOT_FOUND",
                message=message,
            ) from exc
        raise InvalidRequestError(code="REVIEW_ATTEMPT_INVALID", message=message) from exc
    except ReviewAttemptConflictError as exc:
        raise InvalidRequestError(
            code="REVIEW_ATTEMPT_CONFLICT",
            message=str(exc),
            status_code=409,
        ) from exc
    except ValueError as exc:
        raise InvalidRequestError(code="REVIEW_ATTEMPT_INVALID", message=str(exc)) from exc
    return ReviewAttemptOut.from_result(result)
