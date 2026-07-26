from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...auth import require_owner
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.models import User
from ...learning.models import CardEnrollment
from ...learning.schemas import (
    ChapterEnrollmentStatusOut,
    ChapterEnrollmentStatusUpdate,
    EnrollmentBatchOut,
    EnrollmentOut,
    EnrollmentRequest,
    EnrollmentStatusUpdate,
)
from ...learning.services import (
    EnrollmentReferenceError,
    EnrollmentStateError,
    change_chapter_enrollment_status,
    change_enrollment_status,
    enroll_scope,
)

router = APIRouter(tags=["learning"])


def _batch_out(result) -> EnrollmentBatchOut:
    return EnrollmentBatchOut(
        scope=result.scope,
        created_count=result.created_count,
        existing_count=result.existing_count,
        card_ids=list(result.card_ids),
        enrollments=[
            EnrollmentOut.model_validate(enrollment, from_attributes=True)
            for enrollment in result.enrollments
        ],
    )


@router.post("/enrollments", response_model=EnrollmentBatchOut)
def create_enrollments(
    body: EnrollmentRequest,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> EnrollmentBatchOut:
    try:
        result = enroll_scope(db, body.to_scope_create(user_id=owner.id))
    except EnrollmentReferenceError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise ResourceNotFoundError(
                code="ENROLLMENT_TARGET_NOT_FOUND", message=message
            ) from exc
        raise InvalidRequestError(code="ENROLLMENT_INVALID", message=message) from exc
    except EnrollmentStateError as exc:
        raise InvalidRequestError(
            code="ENROLLMENT_CONFLICT",
            message=str(exc),
            status_code=409,
        ) from exc
    except ValueError as exc:
        raise InvalidRequestError(code="ENROLLMENT_INVALID", message=str(exc)) from exc
    return _batch_out(result)


# PUT alias: wx.request does not support the PATCH method on real devices.
@router.patch("/enrollments/{enrollment_id}", response_model=EnrollmentOut)
@router.put("/enrollments/{enrollment_id}", response_model=EnrollmentOut)
def patch_enrollment(
    enrollment_id: int,
    body: EnrollmentStatusUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> EnrollmentOut:
    enrollment = db.get(CardEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != owner.id:
        raise ResourceNotFoundError(
            code="ENROLLMENT_NOT_FOUND",
            message="enrollment does not exist",
        )
    try:
        updated = change_enrollment_status(
            db,
            enrollment_id=enrollment_id,
            target_status=body.status,
        )
    except EnrollmentReferenceError as exc:
        raise ResourceNotFoundError(code="ENROLLMENT_NOT_FOUND", message=str(exc)) from exc
    except EnrollmentStateError as exc:
        raise InvalidRequestError(
            code="ENROLLMENT_STATE_INVALID",
            message=str(exc),
            status_code=409,
        ) from exc
    return EnrollmentOut.model_validate(updated, from_attributes=True)


# PUT alias: wx.request does not support the PATCH method on real devices.
@router.patch(
    "/chapters/{chapter_id}/enrollments",
    response_model=ChapterEnrollmentStatusOut,
)
@router.put(
    "/chapters/{chapter_id}/enrollments",
    response_model=ChapterEnrollmentStatusOut,
)
def patch_chapter_enrollments(
    chapter_id: int,
    body: ChapterEnrollmentStatusUpdate,
    db: Session = Depends(get_db),
    owner: User = Depends(require_owner),
) -> ChapterEnrollmentStatusOut:
    try:
        result = change_chapter_enrollment_status(
            db,
            user_id=owner.id,
            chapter_id=chapter_id,
            target_status=body.status,
        )
    except EnrollmentReferenceError as exc:
        message = str(exc)
        if "does not exist" in message:
            raise ResourceNotFoundError(
                code="CHAPTER_NOT_FOUND",
                message=message,
            ) from exc
        raise InvalidRequestError(code="ENROLLMENT_INVALID", message=message) from exc
    except EnrollmentStateError as exc:
        raise InvalidRequestError(
            code="ENROLLMENT_STATE_INVALID",
            message=str(exc),
            status_code=409,
        ) from exc
    return ChapterEnrollmentStatusOut(
        chapter_id=chapter_id,
        status=body.status,
        updated_count=result.updated_count,
        unchanged_count=result.unchanged_count,
        ignored_count=result.ignored_count,
        enrollments=[
            EnrollmentOut.model_validate(enrollment, from_attributes=True)
            for enrollment in result.enrollments
        ],
    )
