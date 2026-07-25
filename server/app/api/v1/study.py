from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.schemas import (
    ReviewAttemptOut,
    ReviewAttemptRequest,
    StudySessionCreate,
    StudySessionOut,
    StudySessionRequest,
)
from ...learning.services import (
    ReviewAttemptConflictError,
    ReviewAttemptReferenceError,
    StudySessionReferenceError,
    StudySessionStateError,
    create_study_session,
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
