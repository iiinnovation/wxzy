"""Chapter-aware PDF split (DOC-002).

Plans 20–30 page physical ranges (prefer chapter boundaries), writes split PDFs
with stable ids, and records source-page maps. Absolute paths never enter the
publication-safe split manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.paths import PIPELINE_DATA_ROOT, ROOT

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

SPLIT_SCHEMA_VERSION = 1
TARGET_MIN_PAGES = 20
TARGET_MAX_PAGES = 30
TARGET_PAGES = 25
# External upload tool rejects >200 MB; leave headroom for size variance.
DEFAULT_MAX_SPLIT_BYTES = 180 * 1024 * 1024

PageTextFn = Callable[[Path, int], str]
PageCountFn = Callable[[Path], int]
ExtractFn = Callable[[Path, list[int], Path], dict[str, Any]]

# Prefer Chinese textbook chapter headings at the start of a page's text.
_CHAPTER_HEADING_RE = re.compile(
    r"(?m)^\s*(?:"
    r"第[零〇一二三四五六七八九十百千0-9]+[章节部分篇]\s*\S+"
    r"|[0-9]{1,2}\s*[、.]\s*\S{1,40}"
    r")\s*$"
)
_TOC_MARKER_RE = re.compile(r"目\s*录")


class SplitError(ValueError):
    """Raised when a PDF cannot be planned or split safely."""


def splits_dir(*, root: Path | None = None) -> Path:
    base = root if root is not None else ROOT
    return base / "data" / "document-pipeline" / "splits"


def relative_posix(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved.is_relative_to(root_resolved):
        return resolved.relative_to(root_resolved).as_posix()
    return resolved.name


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def count_pdf_pages(path: Path) -> int:
    if fitz is None:  # pragma: no cover
        raise SplitError("PyMuPDF (fitz) is required: pip install pymupdf")
    doc = fitz.open(path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def default_page_text(path: Path, page_number: int) -> str:
    """Return text for a 1-based PDF page (best-effort; may be empty for scans)."""
    if fitz is None:  # pragma: no cover
        raise SplitError("PyMuPDF (fitz) is required: pip install pymupdf")
    if page_number < 1:
        raise SplitError(f"page_number must be >= 1, got {page_number}")
    doc = fitz.open(path)
    try:
        if page_number > doc.page_count:
            raise SplitError(f"page {page_number} out of range 1..{doc.page_count}")
        return doc.load_page(page_number - 1).get_text("text") or ""
    finally:
        doc.close()


def extract_pages(
    src: Path, pages: list[int], out: Path, *, root: Path | None = None
) -> dict[str, Any]:
    """Extract 1-based inclusive pages from ``src`` into a new PDF at ``out``.

    Raises SystemExit on bad input for compatibility with the MinerU sample CLI.
    """
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


def extract_pages_strict(
    src: Path, pages: list[int], out: Path, *, root: Path | None = None
) -> dict[str, Any]:
    """Like extract_pages but raises SplitError instead of SystemExit."""
    try:
        return extract_pages(src, pages, out, root=root)
    except SystemExit as exc:
        raise SplitError(str(exc)) from exc


def build_page_map(*, page_start: int, page_end: int) -> list[dict[str, Any]]:
    if page_start < 1 or page_end < page_start:
        raise SplitError(f"invalid page range {page_start}-{page_end}")
    mapping: list[dict[str, Any]] = []
    for offset, source_page in enumerate(range(page_start, page_end + 1)):
        mapping.append(
            {
                "split_page_index": offset,
                "source_pdf_page_index": source_page - 1,
                "source_pdf_page_number": source_page,
                "printed_page_label": None,
                "mapping_confidence": 1.0,
            }
        )
    return mapping


def make_split_id(document_version: str, page_start: int, page_end: int) -> str:
    if not document_version or "/" in document_version or "\\" in document_version:
        raise SplitError(f"invalid document_version: {document_version!r}")
    return f"{document_version}.p{page_start:04d}-{page_end:04d}"


def _normalize_chapter_starts(page_count: int, chapter_starts: Sequence[int] | None) -> list[int]:
    if page_count < 1:
        raise SplitError(f"page_count must be >= 1, got {page_count}")
    starts = {1}
    if chapter_starts:
        for raw in chapter_starts:
            page = int(raw)
            if page < 1 or page > page_count:
                raise SplitError(f"chapter start page {page} out of range 1..{page_count}")
            starts.add(page)
    return sorted(starts)


def _even_window_sizes(
    length: int, *, max_pages: int, target_pages: int, min_pages: int
) -> list[int]:
    """Choose window sizes so each piece is <= max_pages and as even as possible.

    Uses the fewest pieces allowed by ``max_pages``. When averages sit well above
    ``target_pages`` and more pieces still stay >= ``min_pages``, increase count
    toward the target.
    """
    if length <= 0:
        return []
    if length <= max_pages:
        return [length]
    # Soft overflow: avoid awkward 16+15 style splits when barely over max.
    soft_max = max_pages + max(0, min_pages // 4)
    if length <= soft_max:
        return [length]
    n = (length + max_pages - 1) // max_pages
    # Soft pull toward target_pages without creating avoidable short pieces.
    while True:
        avg = length / n
        if avg <= target_pages:
            break
        trial = n + 1
        if (length // trial) < min_pages:
            break
        if (length + trial - 1) // trial > max_pages:
            break
        n = trial
    base = length // n
    extra = length % n
    return [base + (1 if i < extra else 0) for i in range(n)]


def _chunk_span(
    start: int,
    end: int,
    *,
    min_pages: int,
    max_pages: int,
    target_pages: int,
    boundary_reason: str,
    chapter_title: str | None,
) -> list[dict[str, Any]]:
    """Split inclusive [start, end] into ~20–30 page windows."""
    if end < start:
        raise SplitError(f"invalid span {start}-{end}")
    length = end - start + 1
    sizes = _even_window_sizes(
        length, max_pages=max_pages, target_pages=target_pages, min_pages=min_pages
    )
    pieces: list[dict[str, Any]] = []
    cursor = start
    multi = len(sizes) > 1
    for size in sizes:
        piece_end = cursor + size - 1
        if multi and boundary_reason.startswith("chapter"):
            reason = "chapter_subsplit"
        elif multi and boundary_reason == "fallback_window":
            reason = "fallback_window"
        else:
            reason = boundary_reason
        pieces.append(
            {
                "page_start": cursor,
                "page_end": piece_end,
                "page_count": size,
                "boundary_reason": reason,
                "chapter_title": chapter_title,
            }
        )
        cursor = piece_end + 1
    if cursor != end + 1:
        raise SplitError(f"internal span packing error for {start}-{end}")
    return pieces


def plan_page_ranges(
    page_count: int,
    *,
    chapter_starts: Sequence[int] | None = None,
    min_pages: int = TARGET_MIN_PAGES,
    max_pages: int = TARGET_MAX_PAGES,
    target_pages: int = TARGET_PAGES,
) -> list[dict[str, Any]]:
    """Plan non-overlapping inclusive 1-based page ranges covering 1..page_count."""
    if min_pages < 1 or max_pages < min_pages or target_pages < 1:
        raise SplitError("invalid min/max/target page parameters")
    if target_pages > max_pages:
        target_pages = max_pages
    if page_count < 1:
        raise SplitError(f"page_count must be >= 1, got {page_count}")

    starts = _normalize_chapter_starts(page_count, chapter_starts)
    has_real_chapters = len(starts) > 1
    ranges: list[dict[str, Any]] = []

    for idx, start in enumerate(starts):
        end = (starts[idx + 1] - 1) if idx + 1 < len(starts) else page_count
        reason = "chapter" if has_real_chapters else "fallback_window"
        ranges.extend(
            _chunk_span(
                start,
                end,
                min_pages=min_pages,
                max_pages=max_pages,
                target_pages=target_pages,
                boundary_reason=reason,
                chapter_title=None,
            )
        )

    # Repair short tails: merge when possible, otherwise rebalance from previous.
    merged = _repair_short_tails(
        ranges,
        min_pages=min_pages,
        max_pages=max_pages,
    )

    _assert_exact_coverage(page_count, merged)
    return merged


def _repair_short_tails(
    ranges: Sequence[dict[str, Any]],
    *,
    min_pages: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    """Avoid final fragments shorter than min_pages when rebalancing is possible."""
    if not ranges:
        return []
    out = [dict(item) for item in ranges]
    i = 0
    while i < len(out):
        item = out[i]
        if item["page_count"] >= min_pages or len(out) == 1:
            i += 1
            continue
        if i == 0:
            # Leading short fragment: try absorb into next.
            if len(out) > 1 and item["page_count"] + out[1]["page_count"] <= max_pages:
                nxt = out[1]
                nxt["page_start"] = item["page_start"]
                nxt["page_count"] = nxt["page_end"] - nxt["page_start"] + 1
                nxt["boundary_reason"] = "merged_short_head"
                out.pop(0)
                continue
            i += 1
            continue
        prev = out[i - 1]
        if prev["page_count"] + item["page_count"] <= max_pages:
            prev["page_end"] = item["page_end"]
            prev["page_count"] = prev["page_end"] - prev["page_start"] + 1
            if prev["boundary_reason"] != item["boundary_reason"]:
                prev["boundary_reason"] = "merged_short_tail"
            out.pop(i)
            continue
        # Steal pages from previous so the short piece reaches min_pages,
        # without shrinking previous below min_pages when avoidable.
        need = min_pages - item["page_count"]
        can_give = prev["page_count"] - min_pages
        if can_give <= 0:
            i += 1
            continue
        give = min(need, can_give)
        prev["page_end"] -= give
        prev["page_count"] = prev["page_end"] - prev["page_start"] + 1
        item["page_start"] -= give
        item["page_count"] = item["page_end"] - item["page_start"] + 1
        item["boundary_reason"] = "rebalanced_short_tail"
        i += 1
    return out


def _assert_exact_coverage(page_count: int, ranges: Sequence[dict[str, Any]]) -> None:
    seen: list[int] = []
    for item in ranges:
        start = int(item["page_start"])
        end = int(item["page_end"])
        if end < start:
            raise SplitError(f"invalid planned range {start}-{end}")
        seen.extend(range(start, end + 1))
    if seen != list(range(1, page_count + 1)):
        missing = sorted(set(range(1, page_count + 1)) - set(seen))
        dupes = sorted({p for p in seen if seen.count(p) > 1})
        raise SplitError(
            f"planned ranges do not cover source pages exactly once "
            f"(missing={missing[:20]}, duplicates={dupes[:20]})"
        )


def detect_chapter_starts(
    src: Path,
    *,
    page_count: int | None = None,
    page_text_fn: PageTextFn | None = None,
    max_scan_pages: int | None = None,
) -> list[int]:
    """Best-effort chapter start pages from per-page text heuristics.

    Returns only pages after 1 (page 1 is always an implicit segment start).
    Empty list means "use fallback windows".
    """
    text_fn = page_text_fn if page_text_fn is not None else default_page_text
    total = page_count if page_count is not None else count_pdf_pages(src)
    if total < 1:
        return []
    limit = total if max_scan_pages is None else min(total, max_scan_pages)
    starts: list[int] = []
    toc_pages = 0
    for page in range(1, limit + 1):
        text = text_fn(src, page)
        head = "\n".join(text.splitlines()[:12])
        if _TOC_MARKER_RE.search(head) and page <= 15:
            toc_pages += 1
            continue
        # Skip pure TOC region for chapter starts; look in body.
        if page <= toc_pages + 1 and toc_pages:
            continue
        if _CHAPTER_HEADING_RE.search(head):
            # Avoid dense false positives: require heading-ish short first line.
            first = next((ln.strip() for ln in head.splitlines() if ln.strip()), "")
            if 2 <= len(first) <= 40:
                starts.append(page)
    # Drop page 1 if present; keep unique sorted.
    return sorted({p for p in starts if p > 1})


def coverage_report(page_count: int, ranges: Sequence[dict[str, Any]]) -> dict[str, Any]:
    seen: list[int] = []
    for item in ranges:
        seen.extend(range(int(item["page_start"]), int(item["page_end"]) + 1))
    missing = sorted(set(range(1, page_count + 1)) - set(seen))
    dupes = sorted({p for p in seen if seen.count(p) > 1})
    return {
        "source_pages_covered": len(set(seen)),
        "missing_pages": missing,
        "duplicate_pages": dupes,
        "exact": not missing and not dupes and len(seen) == page_count,
    }


def plan_document_splits(
    *,
    document_key: str,
    document_version: str,
    source_file_name: str,
    source_sha256: str | None,
    page_count: int,
    chapter_starts: Sequence[int] | None = None,
    min_pages: int = TARGET_MIN_PAGES,
    max_pages: int = TARGET_MAX_PAGES,
    target_pages: int = TARGET_PAGES,
    max_split_bytes: int = DEFAULT_MAX_SPLIT_BYTES,
) -> dict[str, Any]:
    ranges = plan_page_ranges(
        page_count,
        chapter_starts=chapter_starts,
        min_pages=min_pages,
        max_pages=max_pages,
        target_pages=target_pages,
    )
    splits: list[dict[str, Any]] = []
    for item in ranges:
        page_start = int(item["page_start"])
        page_end = int(item["page_end"])
        split_id = make_split_id(document_version, page_start, page_end)
        splits.append(
            {
                "split_id": split_id,
                "page_start": page_start,
                "page_end": page_end,
                "page_count": page_end - page_start + 1,
                "boundary_reason": item["boundary_reason"],
                "chapter_title": item.get("chapter_title"),
                "output_relpath": (
                    f"data/document-pipeline/splits/{document_version}/{split_id}.pdf"
                ),
                "page_map": build_page_map(page_start=page_start, page_end=page_end),
            }
        )
    return {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "document_key": document_key,
        "document_version": document_version,
        "source_file_name": source_file_name,
        "source_sha256": source_sha256,
        "source_page_count": page_count,
        "target_pages_min": min_pages,
        "target_pages_max": max_pages,
        "target_pages": target_pages,
        "max_split_bytes": max_split_bytes,
        "split_count": len(splits),
        "splits": splits,
        "coverage": coverage_report(page_count, ranges),
    }


def write_split_pdfs(
    plan: dict[str, Any],
    *,
    source_path: Path,
    root: Path | None = None,
    extract_fn: ExtractFn | None = None,
    max_split_bytes: int | None = None,
) -> dict[str, Any]:
    """Materialize planned split PDFs and attach size/hash metadata."""
    base = root if root is not None else ROOT
    limit = (
        max_split_bytes
        if max_split_bytes is not None
        else int(plan.get("max_split_bytes") or DEFAULT_MAX_SPLIT_BYTES)
    )
    writer = (
        extract_fn
        if extract_fn is not None
        else (lambda src, pages, out: extract_pages_strict(src, pages, out, root=base))
    )
    document_version = str(plan["document_version"])
    out_dir = splits_dir(root=base) / document_version
    out_dir.mkdir(parents=True, exist_ok=True)

    updated_splits: list[dict[str, Any]] = []
    for item in plan["splits"]:
        page_start = int(item["page_start"])
        page_end = int(item["page_end"])
        pages = list(range(page_start, page_end + 1))
        split_id = str(item["split_id"])
        out_path = out_dir / f"{split_id}.pdf"
        meta = writer(source_path, pages, out_path)
        size = int(meta.get("output_size_bytes") or out_path.stat().st_size)
        if size > limit:
            raise SplitError(
                f"split {split_id} is {size} bytes, exceeds max_split_bytes={limit}; "
                "reduce target pages or re-plan"
            )
        record = dict(item)
        record["output_relpath"] = relative_posix(out_path, root=base)
        record["output_size_bytes"] = size
        record["output_sha256"] = sha256_file(out_path)
        record["output_pages"] = int(meta.get("output_pages") or len(pages))
        updated_splits.append(record)

    result = dict(plan)
    result["splits"] = updated_splits
    result["generated_at"] = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    return result


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_inventory_documents(
    inventory_path: Path,
) -> list[dict[str, Any]]:
    if not inventory_path.is_file():
        raise SplitError(f"inventory not found: {inventory_path}")
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    docs = payload.get("documents")
    if not isinstance(docs, list) or not docs:
        raise SplitError(f"inventory has no documents: {inventory_path}")
    return [d for d in docs if isinstance(d, dict)]


def resolve_source_path(
    doc: dict[str, Any],
    *,
    root: Path,
    source_dir: Path | None = None,
    local_manifest_path: Path | None = None,
) -> Path:
    """Resolve a local PDF path without putting abs paths into manifests."""
    name = doc.get("source_file_name")
    if not isinstance(name, str) or not name:
        raise SplitError(f"document missing source_file_name: {doc.get('document_key')}")

    if local_manifest_path is not None and local_manifest_path.is_file():
        local = json.loads(local_manifest_path.read_text(encoding="utf-8"))
        for entry in local.get("sources") or []:
            if not isinstance(entry, dict):
                continue
            if (
                entry.get("document_key") == doc.get("document_key")
                or entry.get("source_file_name") == name
            ):
                abs_path = entry.get("source_abs_path")
                if isinstance(abs_path, str) and abs_path:
                    path = Path(abs_path)
                    if path.is_file():
                        return path

    sources = source_dir if source_dir is not None else root / "docs"
    candidate = sources / name
    if candidate.is_file():
        return candidate
    rel = doc.get("source_relpath")
    if isinstance(rel, str) and rel:
        alt = root / rel
        if alt.is_file():
            return alt
    raise SplitError(f"source PDF not found for {doc.get('document_key')}: {name}")


def split_document(
    *,
    document: dict[str, Any],
    source_path: Path,
    root: Path | None = None,
    chapter_starts: Sequence[int] | None = None,
    detect_chapters: bool = True,
    page_text_fn: PageTextFn | None = None,
    page_count_fn: PageCountFn | None = None,
    extract_fn: ExtractFn | None = None,
    min_pages: int = TARGET_MIN_PAGES,
    max_pages: int = TARGET_MAX_PAGES,
    target_pages: int = TARGET_PAGES,
    max_split_bytes: int = DEFAULT_MAX_SPLIT_BYTES,
    write_pdfs: bool = True,
) -> dict[str, Any]:
    base = root if root is not None else ROOT
    document_key = str(document["document_key"])
    document_version = str(document["document_version"])
    source_file_name = str(document["source_file_name"])
    source_sha256 = document.get("source_sha256")
    if isinstance(source_sha256, str):
        sha = source_sha256
    else:
        sha = None

    counter = page_count_fn if page_count_fn is not None else count_pdf_pages
    page_count = int(document.get("page_count") or counter(source_path))
    if page_count_fn is None and int(document.get("page_count") or 0) not in (0, page_count):
        # Prefer live count when inventory is stale.
        page_count = counter(source_path)

    starts: list[int] | None
    if chapter_starts is not None:
        starts = list(chapter_starts)
    elif detect_chapters:
        starts = detect_chapter_starts(
            source_path,
            page_count=page_count,
            page_text_fn=page_text_fn,
        )
    else:
        starts = []

    plan = plan_document_splits(
        document_key=document_key,
        document_version=document_version,
        source_file_name=source_file_name,
        source_sha256=sha,
        page_count=page_count,
        chapter_starts=starts,
        min_pages=min_pages,
        max_pages=max_pages,
        target_pages=target_pages,
        max_split_bytes=max_split_bytes,
    )
    plan["chapter_starts"] = starts or []
    if not write_pdfs:
        plan["generated_at"] = (
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        return plan
    return write_split_pdfs(
        plan,
        source_path=source_path,
        root=base,
        extract_fn=extract_fn,
        max_split_bytes=max_split_bytes,
    )


def run_split_corpus(
    *,
    root: Path | None = None,
    inventory_path: Path | None = None,
    local_manifest_path: Path | None = None,
    source_dir: Path | None = None,
    document_keys: Sequence[str] | None = None,
    detect_chapters: bool = True,
    write_pdfs: bool = True,
    min_pages: int = TARGET_MIN_PAGES,
    max_pages: int = TARGET_MAX_PAGES,
    target_pages: int = TARGET_PAGES,
    max_split_bytes: int = DEFAULT_MAX_SPLIT_BYTES,
    page_text_fn: PageTextFn | None = None,
    page_count_fn: PageCountFn | None = None,
    extract_fn: ExtractFn | None = None,
) -> dict[str, Any]:
    base = root if root is not None else ROOT
    inv_path = (
        inventory_path
        if inventory_path is not None
        else base / "data" / "document-pipeline" / "inventory" / "documents.v1.json"
    )
    local_path = (
        local_manifest_path
        if local_manifest_path is not None
        else base / "data" / "document-pipeline" / "inventory" / "local_sources.v1.json"
    )
    docs = load_inventory_documents(inv_path)
    if document_keys is not None:
        wanted = set(document_keys)
        docs = [d for d in docs if d.get("document_key") in wanted]
        if not docs:
            raise SplitError(f"no inventory documents match keys: {sorted(wanted)}")

    manifests: list[dict[str, Any]] = []
    for doc in docs:
        source_path = resolve_source_path(
            doc,
            root=base,
            source_dir=source_dir,
            local_manifest_path=local_path if local_path.is_file() else None,
        )
        manifest = split_document(
            document=doc,
            source_path=source_path,
            root=base,
            detect_chapters=detect_chapters,
            page_text_fn=page_text_fn,
            page_count_fn=page_count_fn,
            extract_fn=extract_fn,
            min_pages=min_pages,
            max_pages=max_pages,
            target_pages=target_pages,
            max_split_bytes=max_split_bytes,
            write_pdfs=write_pdfs,
        )
        out_manifest = (
            splits_dir(root=base) / str(manifest["document_version"]) / "split-manifest.json"
        )
        write_json(out_manifest, manifest)
        manifests.append(
            {
                "document_key": manifest["document_key"],
                "document_version": manifest["document_version"],
                "split_count": manifest["split_count"],
                "source_page_count": manifest["source_page_count"],
                "manifest_relpath": relative_posix(out_manifest, root=base),
                "coverage_exact": bool(manifest.get("coverage", {}).get("exact")),
            }
        )

    summary = {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "document_count": len(manifests),
        "split_total": sum(int(m["split_count"]) for m in manifests),
        "page_total": sum(int(m["source_page_count"]) for m in manifests),
        "documents": manifests,
    }
    summary_path = splits_dir(root=base) / "split-summary.v1.json"
    write_json(summary_path, summary)
    summary["summary_relpath"] = relative_posix(summary_path, root=base)
    return summary


__all__ = [
    "DEFAULT_MAX_SPLIT_BYTES",
    "PIPELINE_DATA_ROOT",
    "SPLIT_SCHEMA_VERSION",
    "TARGET_MAX_PAGES",
    "TARGET_MIN_PAGES",
    "TARGET_PAGES",
    "SplitError",
    "build_page_map",
    "count_pdf_pages",
    "coverage_report",
    "default_page_text",
    "detect_chapter_starts",
    "extract_pages",
    "extract_pages_strict",
    "load_inventory_documents",
    "make_split_id",
    "plan_document_splits",
    "plan_page_ranges",
    "resolve_source_path",
    "run_split_corpus",
    "split_document",
    "splits_dir",
    "write_json",
    "write_split_pdfs",
]
