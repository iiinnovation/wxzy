"""Document processing pipeline package for wxzy.

Stages (see docs/superpowers/specs/2026-07-22-document-processing-design.md):

    inventory -> split -> submit/poll/download -> raw -> clean
      -> structure -> quality -> candidates -> review -> publish

CLI compatibility wrappers remain at tools/mineru_validate.py and
tools/generate_candidate_cards.py.
"""

from __future__ import annotations

__all__ = [
    "ROOT",
    "PIPELINE_DATA_ROOT",
    "DEFAULT_MINERU_BASE",
    "MINERU_DAILY_FILE_BUDGET",
    "MINERU_DAILY_PAGE_BUDGET",
]

from tools.document_pipeline.budget import (
    MINERU_DAILY_FILE_BUDGET,
    MINERU_DAILY_PAGE_BUDGET,
)
from tools.document_pipeline.paths import (
    DEFAULT_MINERU_BASE,
    PIPELINE_DATA_ROOT,
    ROOT,
)
