from fastapi import APIRouter

from ...routers import admin, books, cards, review, stats

router = APIRouter(prefix="/api/v1")
router.include_router(books.router)
router.include_router(cards.router)
router.include_router(review.router)
router.include_router(stats.router)
router.include_router(admin.router)
