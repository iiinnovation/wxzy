"""MinerU daily budget helpers.

Operator-reported quotas (2026-07-23):
  - 5000 files/day (submission file count)
  - 1000 priority parse pages/day

File quota is not the bottleneck for the 704-page corpus. Page priority budget
is the throttle for full runs. P3-T04 job lifecycle should enforce these via
manifest counters; this module only provides pure accounting helpers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Defaults match operator-reported MinerU plan limits.
MINERU_DAILY_FILE_BUDGET = 5000
MINERU_DAILY_PAGE_BUDGET = 1000

# Conservative batch size from design (4–8 splits per batch).
DEFAULT_BATCH_SPLIT_COUNT = 6


def daily_file_budget() -> int:
    raw = os.environ.get("MINERU_DAILY_FILE_BUDGET")
    if raw is None or not raw.strip():
        return MINERU_DAILY_FILE_BUDGET
    return max(0, int(raw))


def daily_page_budget() -> int:
    raw = os.environ.get("MINERU_DAILY_PAGE_BUDGET")
    if raw is None or not raw.strip():
        return MINERU_DAILY_PAGE_BUDGET
    return max(0, int(raw))


@dataclass(frozen=True)
class BudgetSnapshot:
    file_budget: int
    page_budget: int
    files_used: int
    pages_used: int

    @property
    def files_remaining(self) -> int:
        return max(0, self.file_budget - self.files_used)

    @property
    def pages_remaining(self) -> int:
        return max(0, self.page_budget - self.pages_used)

    def can_accept(self, *, files: int, pages: int) -> bool:
        if files < 0 or pages < 0:
            raise ValueError("files and pages must be non-negative")
        return files <= self.files_remaining and pages <= self.pages_remaining

    def reserve(self, *, files: int, pages: int) -> BudgetSnapshot:
        if not self.can_accept(files=files, pages=pages):
            raise ValueError(
                f"budget exceeded: need files={files} pages={pages}, "
                f"remaining files={self.files_remaining} pages={self.pages_remaining}"
            )
        return BudgetSnapshot(
            file_budget=self.file_budget,
            page_budget=self.page_budget,
            files_used=self.files_used + files,
            pages_used=self.pages_used + pages,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_budget": self.file_budget,
            "page_budget": self.page_budget,
            "files_used": self.files_used,
            "pages_used": self.pages_used,
            "files_remaining": self.files_remaining,
            "pages_remaining": self.pages_remaining,
        }


def fresh_budget(
    *,
    file_budget: int | None = None,
    page_budget: int | None = None,
    files_used: int = 0,
    pages_used: int = 0,
) -> BudgetSnapshot:
    return BudgetSnapshot(
        file_budget=file_budget if file_budget is not None else daily_file_budget(),
        page_budget=page_budget if page_budget is not None else daily_page_budget(),
        files_used=files_used,
        pages_used=pages_used,
    )


def estimate_split_count(
    page_count: int,
    *,
    target_pages_per_split: int = 25,
) -> int:
    """Rough split count for a book under chapter-aware 20–30 page targets."""
    if page_count <= 0:
        return 0
    if target_pages_per_split <= 0:
        raise ValueError("target_pages_per_split must be positive")
    return (page_count + target_pages_per_split - 1) // target_pages_per_split


def corpus_budget_assessment(
    *,
    page_total: int = 704,
    file_budget: int | None = None,
    page_budget: int | None = None,
    target_pages_per_split: int = 25,
) -> dict[str, Any]:
    """Planning helper: does a full corpus pass fit one priority day?"""
    fb = file_budget if file_budget is not None else daily_file_budget()
    pb = page_budget if page_budget is not None else daily_page_budget()
    split_est = estimate_split_count(page_total, target_pages_per_split=target_pages_per_split)
    days_by_pages = 0 if page_total == 0 else (page_total + max(pb, 1) - 1) // max(pb, 1)
    days_by_files = 0 if split_est == 0 else (split_est + max(fb, 1) - 1) // max(fb, 1)
    return {
        "page_total": page_total,
        "estimated_splits": split_est,
        "file_budget": fb,
        "page_budget": pb,
        "fits_file_budget_one_day": split_est <= fb,
        "fits_page_budget_one_day": page_total <= pb,
        "min_days_by_pages": days_by_pages,
        "min_days_by_files": days_by_files,
        "bottleneck": "pages" if days_by_pages >= days_by_files else "files",
        "notes": [
            "File quota (default 5000/day) is not binding for ~28–35 splits.",
            "Priority page budget (default 1000/day) is the throttle for full 704-page runs.",
            "Reuse successful raw outputs; never re-submit done splits against the page budget.",
        ],
    }
