from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1.router import router as v1_router
from .config import get_settings
from .core.errors import install_exception_handlers
from .core.logging import configure_logging, request_context_middleware
from .routers import admin, books, cards, review, stats
from .schemas import HealthOut

settings = get_settings()
configure_logging()

app = FastAPI(title=settings.app_name, version="0.1.0")
install_exception_handlers(app)
app.middleware("http")(request_context_middleware)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.include_router(v1_router)
app.include_router(books.router, deprecated=True)
app.include_router(cards.router, deprecated=True)
app.include_router(review.router, deprecated=True)
app.include_router(admin.router, deprecated=True)
app.include_router(stats.router, deprecated=True)


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", app=settings.app_name, time=datetime.now(UTC))
