"""PDF page vs printed page mapping for cleaned MinerU outputs.

P3-T06: keep source_pdf_page_* separate from printed_page_label; never collapse
them into one integer. Mapping is deterministic from content_list page_number
items plus the split page_map skeleton.
"""

from __future__ import annotations

import re
from typing import Any

from tools.document_pipeline.structure import load_content_list, page_number

PRINTED_LABEL_RE = re.compile(r"^\s*/?\s*(\d{1,5})\s*$")


def normalize_printed_page_label(text: Any) -> str | None:
    """Extract a printable page label string; preserve digits only semantics."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    m = PRINTED_LABEL_RE.match(raw)
    if m:
        return m.group(1)
    # Keep short non-numeric labels (roman, etc.) without inventing integers.
    if len(raw) <= 12 and not any(ch.isspace() for ch in raw):
        return raw
    return None


def extract_printed_labels_from_content_list(
    items: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Map split_page_index (content_list page_idx) -> printed label evidence.

    Uses type==page_number entries only. When multiple labels exist for one page,
    prefers the first non-empty normalized label and records all raw texts.
    """
    by_page: dict[int, dict[str, Any]] = {}
    for it in items:
        if str(it.get("type") or "") != "page_number":
            continue
        idx = page_number(it.get("page_idx"))
        if idx is None or idx < 0:
            continue
        raw_text = it.get("text") or it.get("content") or ""
        if isinstance(raw_text, list):
            raw_text = " ".join(str(x) for x in raw_text)
        raw_text = str(raw_text).strip()
        label = normalize_printed_page_label(raw_text)
        slot = by_page.setdefault(
            idx,
            {"printed_page_label": None, "raw_texts": [], "evidence_count": 0},
        )
        if raw_text:
            slot["raw_texts"].append(raw_text)
            slot["evidence_count"] += 1
        if slot["printed_page_label"] is None and label is not None:
            slot["printed_page_label"] = label
    return by_page


def confidence_for_printed_label(
    *,
    label: str | None,
    evidence_count: int,
    contiguous_hint: bool | None = None,
) -> float:
    """Deterministic confidence in [0, 1] for a printed-page mapping row."""
    if label is None:
        return 0.0 if evidence_count == 0 else 0.25
    if evidence_count <= 0:
        return 0.5
    base = 0.9 if evidence_count == 1 else 0.95
    if contiguous_hint is False:
        base = max(0.5, base - 0.15)
    return round(base, 3)


def build_page_map_from_content_list(
    items: list[dict[str, Any]],
    *,
    source_pdf_page_start: int | None = None,
    expected_page_count: int | None = None,
    base_page_map: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a full page_map separating PDF indices from printed labels.

    Parameters
    ----------
    items:
        MinerU content_list entries.
    source_pdf_page_start:
        1-based first page of this split in the source PDF. When base_page_map
        is provided, its source fields win.
    expected_page_count:
        When set, emit exactly this many rows (0..n-1). Missing content_list
        pages still get PDF indices with null printed labels.
    base_page_map:
        Optional split-time skeleton from ``split.build_page_map``.
    """
    printed = extract_printed_labels_from_content_list(items)
    page_idxs_from_items = sorted(
        {p for it in items if (p := page_number(it.get("page_idx"))) is not None and p >= 0}
    )

    if base_page_map:
        rows = [dict(row) for row in base_page_map]
        # Ensure required keys exist
        for row in rows:
            row.setdefault("split_page_index", None)
            row.setdefault("source_pdf_page_index", None)
            row.setdefault("source_pdf_page_number", None)
            row.setdefault("printed_page_label", None)
            row.setdefault("mapping_confidence", 1.0)
    else:
        if expected_page_count is not None:
            indices = list(range(expected_page_count))
        elif page_idxs_from_items:
            indices = list(range(min(page_idxs_from_items), max(page_idxs_from_items) + 1))
        else:
            indices = []
        if source_pdf_page_start is None:
            source_pdf_page_start = 1
        if source_pdf_page_start < 1:
            raise ValueError(f"source_pdf_page_start must be >= 1, got {source_pdf_page_start}")
        rows = []
        for offset in indices:
            source_page = source_pdf_page_start + offset
            rows.append(
                {
                    "split_page_index": offset,
                    "source_pdf_page_index": source_page - 1,
                    "source_pdf_page_number": source_page,
                    "printed_page_label": None,
                    "mapping_confidence": 1.0,
                }
            )

    # Contiguity of printed labels (numeric only) for confidence adjust
    numeric_labels: list[tuple[int, int]] = []
    for row in rows:
        idx = int(row["split_page_index"])
        evidence = printed.get(idx)
        if not evidence:
            continue
        label = evidence.get("printed_page_label")
        if label is not None and str(label).isdigit():
            numeric_labels.append((idx, int(str(label))))

    contiguous_by_idx: dict[int, bool] = {}
    for i, (idx, val) in enumerate(numeric_labels):
        ok = True
        if i > 0:
            prev_idx, prev_val = numeric_labels[i - 1]
            # non-contiguous split pages may skip; only check consecutive split pages
            if idx == prev_idx + 1 and val != prev_val + 1:
                ok = False
        contiguous_by_idx[idx] = ok

    for row in rows:
        idx = int(row["split_page_index"])
        evidence = printed.get(idx)
        if evidence:
            label = evidence.get("printed_page_label")
            row["printed_page_label"] = label
            row["printed_raw_texts"] = list(evidence.get("raw_texts") or [])
            row["mapping_confidence"] = confidence_for_printed_label(
                label=label if label is not None else None,
                evidence_count=int(evidence.get("evidence_count") or 0),
                contiguous_hint=contiguous_by_idx.get(idx),
            )
        else:
            # PDF identity still known; printed unknown
            row.setdefault("printed_page_label", None)
            row["printed_raw_texts"] = []
            # Keep high confidence on PDF identity mapping when base/skeleton known
            if row.get("source_pdf_page_number") is not None:
                row["mapping_confidence"] = (
                    1.0
                    if row.get("printed_page_label") is None
                    else row.get("mapping_confidence", 1.0)
                )
            else:
                row["mapping_confidence"] = 0.0

    return rows


def page_map_coverage(page_map: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute mapping coverage stats for acceptance (100% PDF rows present)."""
    n = len(page_map)
    with_pdf = 0
    with_printed = 0
    indices: list[int] = []
    for row in page_map:
        idx = row.get("split_page_index")
        if isinstance(idx, int):
            indices.append(idx)
        if (
            row.get("source_pdf_page_index") is not None
            and row.get("source_pdf_page_number") is not None
        ):
            with_pdf += 1
        if row.get("printed_page_label") not in (None, ""):
            with_printed += 1
    expected = list(range(n)) if n else []
    contiguous = sorted(indices) == expected
    return {
        "page_count": n,
        "pdf_mapped_count": with_pdf,
        "printed_mapped_count": with_printed,
        "pdf_coverage": 1.0 if n and with_pdf == n else (0.0 if n == 0 else round(with_pdf / n, 4)),
        "printed_coverage": 0.0 if n == 0 else round(with_printed / n, 4),
        "split_indices_contiguous": contiguous,
        "complete": bool(n and with_pdf == n and contiguous),
    }


def enrich_page_map_from_content_list_path(
    content_list_path: Any,
    *,
    source_pdf_page_start: int | None = None,
    expected_page_count: int | None = None,
    base_page_map: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Load content_list from path and build page_map."""
    from pathlib import Path

    path = Path(content_list_path) if content_list_path is not None else None
    items = load_content_list(path)
    return build_page_map_from_content_list(
        items,
        source_pdf_page_start=source_pdf_page_start,
        expected_page_count=expected_page_count,
        base_page_map=base_page_map,
    )


__all__ = [
    "PRINTED_LABEL_RE",
    "build_page_map_from_content_list",
    "confidence_for_printed_label",
    "enrich_page_map_from_content_list_path",
    "extract_printed_labels_from_content_list",
    "normalize_printed_page_label",
    "page_map_coverage",
]
