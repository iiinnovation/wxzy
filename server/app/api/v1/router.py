from fastapi import APIRouter

from ...routers import admin, books, cards, review, stats
from .catalog import router as catalog_router
from .enrollments import router as enrollments_router
from .identity import router as identity_router
from .insights import router as insights_router
from .learning_coach import router as learning_coach_router
from .learning_today import router as learning_today_router
from .study import router as study_router

router = APIRouter(prefix="/api/v1")
router.include_router(identity_router)
router.include_router(catalog_router)
router.include_router(insights_router)
router.include_router(enrollments_router)
router.include_router(study_router)
router.include_router(learning_coach_router)
router.include_router(learning_today_router)
router.include_router(books.router)
router.include_router(cards.router)
router.include_router(review.router)
router.include_router(stats.router)
router.include_router(admin.router)
