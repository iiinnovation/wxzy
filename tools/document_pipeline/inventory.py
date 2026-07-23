"""Document inventory scaffolding (full scan lands in P3-T02)."""

from __future__ import annotations

from typing import Any

from tools.document_pipeline.paths import (
    CORPUS_PAGE_TOTAL,
    DOCUMENT_KEYS,
    DOCUMENT_PAGE_COUNTS,
)


def planned_document_keys() -> list[str]:
    return list(DOCUMENT_KEYS.keys())


def planned_corpus_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "document_count": len(DOCUMENT_KEYS),
        "page_total": CORPUS_PAGE_TOTAL,
        "documents": [
            {
                "document_key": key,
                "source_file_name": DOCUMENT_KEYS[key],
                "planned_page_count": DOCUMENT_PAGE_COUNTS[key],
            }
            for key in DOCUMENT_KEYS
        ],
    }
