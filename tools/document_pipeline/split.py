"""PDF page extraction helpers (physical split building block)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.document_pipeline.paths import ROOT

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


def extract_pages(
    src: Path, pages: list[int], out: Path, *, root: Path | None = None
) -> dict[str, Any]:
    """Extract 1-based inclusive pages from ``src`` into a new PDF at ``out``."""
    if fitz is None:
        raise SystemExit("PyMuPDF (fitz) is required: pip install pymupdf")
    if not src.is_file():
        raise SystemExit(f"source PDF not found: {src}")
    base = root if root is not None else ROOT
    doc = fitz.open(src)
    total = doc.page_count
    selected: list[int] = []
    for p in pages:
        if p < 1 or p > total:
            raise SystemExit(f"page {p} out of range 1..{total} for {src.name}")
        selected.append(p - 1)
    new_doc = fitz.open()
    for idx in selected:
        new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_doc.save(out)
    meta = {
        "source": str(src.relative_to(base)) if src.is_relative_to(base) else str(src),
        "source_pages_total": total,
        "selected_pages_1based": pages,
        "output": str(out.relative_to(base)) if out.is_relative_to(base) else str(out),
        "output_pages": new_doc.page_count,
        "output_size_bytes": out.stat().st_size,
    }
    new_doc.close()
    doc.close()
    return meta
