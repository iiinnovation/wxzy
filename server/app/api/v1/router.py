from fastapi import APIRouter

from ...routers import admin, books, cards, review, stats
from .enrollments import router as enrollments_router
from .identity import router as identity_router
from .study import router as study_router

router = APIRouter(prefix="/api/v1")
router.include_router(identity_router)
router.include_router(enrollments_router)
router.include_router(study_router)
router.include_router(books.router)
router.include_router(cards.router)
router.include_router(review.router)
router.include_router(stats.router)
router.include_router(admin.router)
