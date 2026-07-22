from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BookOut(BaseModel):
    id: int
    name: str
    subject: str | None = None
    card_count: int = 0

    model_config = {"from_attributes": True}


class CardOut(BaseModel):
    id: int
    external_id: str
    book_id: int
    book_name: str | None = None
    chapter: str | None = None
    section: str | None = None
    card_type: str
    question: str
    answer: str
    answer_points: list[str] = Field(default_factory=list)
    source_excerpt: str = ""
    source_pages: list[int] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str
    confidence: float | None = None

    model_config = {"from_attributes": True}


class ReviewDueItem(BaseModel):
    card: CardOut
    due_at: datetime
    state: str
    reps: int
    lapses: int
    stability: float
    difficulty: float


class ReviewAnswerIn(BaseModel):
    card_id: int
    rating: int = Field(ge=1, le=4, description="1 again 2 hard 3 good 4 easy")


class ReviewAnswerOut(BaseModel):
    card_id: int
    rating: int
    due_at: datetime
    scheduled_days: float
    stability: float
    difficulty: float
    state: str
    reps: int
    lapses: int
    algorithm_version: str


class ImportResult(BaseModel):
    books_created: int
    cards_upserted: int
    review_states_created: int
    skipped_non_approved: int


class StatsOut(BaseModel):
    books: int
    cards_approved: int
    due_now: int
    reviewed_today: int
    new_cards: int


class HealthOut(BaseModel):
    status: str
    app: str
    time: datetime


class ErrorOut(BaseModel):
    detail: str
