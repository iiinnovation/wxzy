"""Chapter tree, PageRecord, and ContentBlock structuring (P3-T07).

Signals: markdown headings, content_list text_level/layout, running headers,
and adjacent-page continuity. Low-confidence chapter boundaries are marked for
review and do not silently reassign subsequent pages.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.document_pipeline.generation import parse_html_tables
from tools.document_pipeline.raw import (
    RawError,
    assert_not_raw_write_target,
    is_under_raw_tree,
    sha256_bytes,
    sha256_file,
)

STRUCTURE_PIPELINE_VERSION = "structure.v1"
LOW_CHAPTER_CONFIDENCE = 0.6

# Heading patterns common across the seven book templates.
_RE_PART_CHAPTER = re.compile(
    r"^(?P<title>(?:第[一二三四五六七八九十百零〇两\d]+部分\s*)?"
    r".*?(?:第[一二三四五六七八九十百零〇两\d]+章|第[一二三四五六七八九十百零〇两\d]+节).*)"
)
_RE_CHAPTER = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+章\s*.+")
_RE_SECTION = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+节\s*.+")
_RE_NUMBERED = re.compile(r"^(?:\d+|[一二三四五六七八九十]+)[\.、．]\s*.+")
_RE_PAREN_ITEM = re.compile(r"^[（(]\d+[）)]\s*.+")
_RE_RUNNING_HEADER = re.compile(
    r"^(?:中医考研\s*)?(?:学霸|学朝|学期)\s*笔记$|"
    r"^中医考研\s*(?:学霸|学朝|学期)\s*笔记$|"
    r"^第四部分\s*$|"
    r"^第[一二三四五六七八九十]+部分\s*$"
)
_RE_PIPE_RUNNING = re.compile(
    r"^(?P<left>.+?)\s*\|\s*(?P<right>第[一二三四五六七八九十百零〇两\d]+[章节].+)$"
)
_RE_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_RE_HTML_TABLE = re.compile(r"(?is)<table\b.*?</table>")

# Template keys for the 7-book corpus (acceptance fixtures).
BOOK_TEMPLATE_KEYS: tuple[str, ...] = (
    "jichu",
    "zhenduan",
    "zhongyao",
    "fangji",
    "neike",
    "zhenjiu",
    "renwen",
)

BOOK_TEMPLATE_LABELS: dict[str, str] = {
    "jichu": "中医基础理论",
    "zhenduan": "中医诊断学",
    "zhongyao": "中药学",
    "fangji": "方剂学",
    "neike": "中医内科学",
    "zhenjiu": "针灸学",
    "renwen": "人文",
}


def stable_chunk_id(
    document_version_id: str,
    *,
    block_type: str,
    source_pdf_pages: list[int],
    ordinal: int,
    content: str,
) -> str:
    """Stable ContentBlock id (repeatable, content-sensitive)."""
    pages = ",".join(str(p) for p in source_pdf_pages)
    digest_src = "|".join(
        [
            document_version_id,
            block_type,
            pages,
            str(ordinal),
            hashlib.sha1(content.encode("utf-8")).hexdigest(),
        ]
    )
    h = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", block_type).strip("-") or "block"
    return f"{slug}-{h}"


def find_md_and_content_list(result_dir: Path) -> tuple[Path | None, Path | None]:
    md: Path | None = None
    cl: Path | None = None
    for p in result_dir.rglob("full.md"):
        md = p
        break
    if md is None:
        mds = list(result_dir.rglob("*.md"))
        if mds:
            md = mds[0]
    for p in result_dir.rglob("*_content_list.json"):
        if p.name.endswith("_content_list_v2.json"):
            continue
        cl = p
        break
    if cl is None:
        v2 = list(result_dir.rglob("*_content_list_v2.json"))
        if v2:
            cl = v2[0]
    return md, cl


def load_content_list(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for key in ("content_list", "pdf_info", "items"):
            items = raw.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def page_number(value: Any) -> int | None:
    """Convert an untrusted content-list page value to a usable integer."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_text(it: dict[str, Any]) -> str:
    text = it.get("text") or it.get("content") or it.get("table_body") or ""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    return str(text).strip()


def _is_noise_heading(title: str) -> bool:
    t = title.strip()
    if not t:
        return True
    if _RE_RUNNING_HEADER.match(t):
        return True
    if re.match(r"^中医考研", t) and "笔记" in t:
        return True
    return False


def classify_heading(title: str) -> dict[str, Any]:
    """Classify a heading string into chapter-tree role with confidence."""
    t = re.sub(r"\s+", " ", title.strip())
    t = t.lstrip("#").strip()
    if _is_noise_heading(t):
        return {
            "title": t,
            "role": "noise",
            "level": None,
            "confidence": 0.95,
            "method": "running_header_filter",
        }

    pipe = _RE_PIPE_RUNNING.match(t)
    if pipe:
        right = pipe.group("right").strip()
        left = pipe.group("left").strip()
        path = [left, right] if left and right else [t]
        level = 1 if "章" in right else 2 if "节" in right else 1
        return {
            "title": t,
            "role": "chapter" if level == 1 else "section",
            "level": level,
            "path_hint": path,
            "confidence": 0.92,
            "method": "pipe_running_header",
        }

    if _RE_CHAPTER.match(t) or ("章" in t and t.startswith("第")):
        return {
            "title": t,
            "role": "chapter",
            "level": 1,
            "path_hint": [t],
            "confidence": 0.9,
            "method": "chapter_pattern",
        }
    if _RE_SECTION.match(t) or (t.startswith("第") and "节" in t[:6]):
        return {
            "title": t,
            "role": "section",
            "level": 2,
            "path_hint": [t],
            "confidence": 0.88,
            "method": "section_pattern",
        }
    if _RE_NUMBERED.match(t):
        return {
            "title": t,
            "role": "subsection",
            "level": 3,
            "path_hint": [t],
            "confidence": 0.75,
            "method": "numbered_heading",
        }
    if _RE_PAREN_ITEM.match(t):
        return {
            "title": t,
            "role": "item",
            "level": 4,
            "path_hint": [t],
            "confidence": 0.55,
            "method": "paren_item",
        }
    # Unknown markdown heading: keep visible but low confidence for tree attach
    return {
        "title": t,
        "role": "unknown",
        "level": 3,
        "path_hint": [t],
        "confidence": 0.45,
        "method": "unclassified_heading",
    }


def extract_markdown_headings(md: str) -> list[dict[str, Any]]:
    """Parse ATX headings with line numbers and classification."""
    out: list[dict[str, Any]] = []
    for line_no, line in enumerate(md.splitlines(), start=1):
        m = _RE_MD_HEADING.match(line)
        if not m:
            continue
        hashes, title = m.group(1), m.group(2)
        info = classify_heading(title)
        info.update(
            {
                "line_no": line_no,
                "md_level": len(hashes),
                "raw_line": line,
            }
        )
        out.append(info)
    return out


def extract_content_list_headings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Headings inferred from content_list text_level / type."""
    out: list[dict[str, Any]] = []
    for ord_i, it in enumerate(items):
        t = str(it.get("type") or "")
        text = _item_text(it)
        if not text:
            continue
        page_idx = page_number(it.get("page_idx"))
        text_level = it.get("text_level")
        is_heading = False
        if t == "text" and text_level is not None:
            try:
                is_heading = int(text_level) <= 2
            except (TypeError, ValueError):
                is_heading = False
        if t in ("title", "heading"):
            is_heading = True
        if not is_heading:
            # Still accept strong chapter/section patterns in body text
            if not (
                _RE_CHAPTER.match(text) or _RE_SECTION.match(text) or _RE_PIPE_RUNNING.match(text)
            ):
                continue
        info = classify_heading(text)
        if info["role"] == "noise":
            continue
        # layout signal boosts confidence slightly
        conf = float(info["confidence"])
        if text_level is not None:
            conf = min(0.98, conf + 0.05)
            info["method"] = f"{info['method']}+layout_text_level"
        info.update(
            {
                "content_list_ordinal": ord_i,
                "split_page_index": page_idx,
                "text_level": text_level,
                "confidence": round(conf, 3),
            }
        )
        out.append(info)
    return out


def _path_from_classification(info: dict[str, Any], current: list[str]) -> list[str]:
    role = info.get("role")
    title = str(info.get("title") or "")
    hint = info.get("path_hint")
    if isinstance(hint, list) and hint and role in ("chapter", "section") and len(hint) >= 2:
        return [str(x) for x in hint]
    path = list(current)
    level = info.get("level")
    if role == "chapter":
        return [title]
    if role == "section":
        if path:
            return path[:1] + [title]
        return [title]
    if role in ("subsection", "item", "unknown"):
        if not path:
            return [title]
        # keep chapter/section stack, replace trailing same-level
        if level == 3:
            base = path[:2] if len(path) >= 2 else path[:1]
            return base + [title]
        if level == 4:
            base = path[:3] if len(path) >= 3 else path
            return base + [title]
        return path + [title]
    return path


def build_chapter_tree(
    *,
    md_headings: list[dict[str, Any]],
    cl_headings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge heading signals into an ordered chapter-boundary list.

    Each boundary keeps ``method`` and ``confidence``. Boundaries with
    confidence < LOW_CHAPTER_CONFIDENCE are flagged ``needs_review`` and do not
    extend the active high-confidence chapter path for subsequent blocks.
    """
    # Prefer markdown order; enrich with content_list-only headings by page.
    events: list[dict[str, Any]] = []
    for h in md_headings:
        if h.get("role") == "noise":
            continue
        events.append({**h, "source": "markdown"})
    for h in cl_headings or []:
        if h.get("role") == "noise":
            continue
        # Skip near-duplicates already in md (same title)
        title = str(h.get("title") or "")
        if any(str(e.get("title") or "") == title for e in events):
            continue
        events.append({**h, "source": "content_list"})

    # Stable order: markdown line_no first, then content_list ordinal
    def sort_key(e: dict[str, Any]) -> tuple[int, int, int]:
        line = int(e["line_no"]) if e.get("line_no") is not None else 10**9
        page = int(e["split_page_index"]) if e.get("split_page_index") is not None else 10**6
        ord_i = int(e["content_list_ordinal"]) if e.get("content_list_ordinal") is not None else 0
        return (line, page, ord_i)

    events.sort(key=sort_key)

    boundaries: list[dict[str, Any]] = []
    active_path: list[str] = []
    for e in events:
        conf = float(e.get("confidence") or 0.0)
        role = e.get("role")
        if role not in ("chapter", "section", "subsection", "item", "unknown"):
            continue
        candidate_path = _path_from_classification(e, active_path)
        low = conf < LOW_CHAPTER_CONFIDENCE
        if not low and role in ("chapter", "section", "subsection"):
            active_path = candidate_path
            assigned_path = candidate_path
            assignment = "assigned"
        elif not low:
            assigned_path = candidate_path
            assignment = "assigned"
        else:
            # Do not update active high-confidence path
            assigned_path = candidate_path
            assignment = "uncertain"
        boundaries.append(
            {
                "title": e.get("title"),
                "role": role,
                "level": e.get("level"),
                "path": assigned_path,
                "active_path_after": list(active_path),
                "method": e.get("method"),
                "confidence": conf,
                "assignment": assignment,
                "needs_review": low,
                "line_no": e.get("line_no"),
                "split_page_index": e.get("split_page_index"),
                "source": e.get("source"),
            }
        )
    return boundaries


def _chapter_for_line(boundaries: list[dict[str, Any]], line_no: int) -> dict[str, Any]:
    """Resolve chapter assignment for a 1-based line without silent low-conf attach."""
    active: list[str] = []
    method = "none"
    confidence = 1.0
    assignment = "unassigned"
    needs_review = False
    title = None
    for b in boundaries:
        b_line = b.get("line_no")
        if b_line is None:
            continue
        if int(b_line) > line_no:
            break
        if b.get("assignment") == "assigned" and not b.get("needs_review"):
            active = list(b.get("active_path_after") or b.get("path") or [])
            method = str(b.get("method") or "chapter_boundary")
            confidence = float(b.get("confidence") or 0.0)
            assignment = "assigned"
            needs_review = False
            title = b.get("title")
        elif b.get("needs_review"):
            # low-confidence boundary: freeze previous active path; mark review
            method = str(b.get("method") or "low_confidence_boundary")
            confidence = float(b.get("confidence") or 0.0)
            assignment = "uncertain"
            needs_review = True
            title = b.get("title")
            # path for this span remains previous active (not the uncertain title alone)
    return {
        "chapter_path": active,
        "chapter_title": title,
        "chapter_method": method,
        "chapter_confidence": confidence,
        "chapter_assignment": assignment,
        "chapter_needs_review": needs_review,
    }


def _split_markdown_segments(md: str) -> list[dict[str, Any]]:
    """Split markdown into ordered text/table segments with line ranges."""
    segments: list[dict[str, Any]] = []
    pos = 0
    lines = md.splitlines()
    # Build char offset -> line map via cumulative
    for m in _RE_HTML_TABLE.finditer(md):
        if m.start() > pos:
            pre = md[pos : m.start()]
            if pre.strip():
                start_line = md.count("\n", 0, pos) + 1
                end_line = md.count("\n", 0, m.start()) + 1
                segments.append(
                    {
                        "kind": "text",
                        "text": pre,
                        "start_line": start_line,
                        "end_line": end_line,
                    }
                )
        start_line = md.count("\n", 0, m.start()) + 1
        end_line = md.count("\n", 0, m.end()) + 1
        segments.append(
            {
                "kind": "table",
                "text": m.group(0),
                "start_line": start_line,
                "end_line": end_line,
            }
        )
        pos = m.end()
    if pos < len(md):
        tail = md[pos:]
        if tail.strip():
            start_line = md.count("\n", 0, pos) + 1
            end_line = md.count("\n", 0, len(md)) + 1
            segments.append(
                {
                    "kind": "text",
                    "text": tail,
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
    if not segments and md.strip():
        segments.append(
            {
                "kind": "text",
                "text": md,
                "start_line": 1,
                "end_line": max(1, len(lines)),
            }
        )
    return segments


def _split_text_into_blocks(text: str, base_line: int) -> list[dict[str, Any]]:
    """Further split a text segment into heading / paragraph blocks."""
    blocks: list[dict[str, Any]] = []
    buf: list[str] = []
    buf_start = base_line
    line_no = base_line

    def flush_para() -> None:
        nonlocal buf, buf_start
        body = "\n".join(buf).strip()
        if body:
            blocks.append(
                {
                    "block_type": "paragraph",
                    "text": body + "\n",
                    "start_line": buf_start,
                    "end_line": line_no - 1,
                }
            )
        buf = []

    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        m = _RE_MD_HEADING.match(line)
        if m:
            flush_para()
            title = m.group(2).strip()
            info = classify_heading(title)
            btype = "heading" if info["role"] != "noise" else "noise"
            blocks.append(
                {
                    "block_type": btype,
                    "text": line + "\n",
                    "start_line": line_no,
                    "end_line": line_no,
                    "heading": info,
                }
            )
            buf_start = line_no + 1
        else:
            if not buf:
                buf_start = line_no
            buf.append(line)
        line_no += 1
    flush_para()
    return blocks


def _map_line_to_split_page(
    line_no: int,
    *,
    total_lines: int,
    page_count: int,
) -> int | None:
    """Approximate split_page_index from line position when layout lacks markers."""
    if page_count <= 0 or total_lines <= 0:
        return None
    if page_count == 1:
        return 0
    # Even distribution fallback (explicit method; low confidence)
    ratio = (line_no - 1) / max(total_lines - 1, 1)
    idx = int(round(ratio * (page_count - 1)))
    return max(0, min(page_count - 1, idx))


def _pages_from_page_map(
    split_idx: int | None,
    page_map: list[dict[str, Any]],
) -> tuple[list[int], list[str | None], float]:
    if split_idx is None or not page_map:
        return [], [], 0.0
    for row in page_map:
        if int(row.get("split_page_index", -1)) == int(split_idx):
            src = row.get("source_pdf_page_number")
            printed = row.get("printed_page_label")
            conf = float(row.get("mapping_confidence") or 0.0)
            pages = [int(src)] if src is not None else []
            labels = [printed] if printed is not None else []
            return pages, labels, conf
    return [], [], 0.0


def build_content_blocks(
    md: str,
    *,
    document_version_id: str,
    chapter_boundaries: list[dict[str, Any]],
    page_map: list[dict[str, Any]] | None = None,
    book_template: str | None = None,
) -> list[dict[str, Any]]:
    """Build ordered ContentBlocks with stable ids and raw-page backrefs."""
    page_map = page_map or []
    page_count = len(page_map)
    total_lines = max(1, md.count("\n") + 1)
    segments = _split_markdown_segments(md)
    raw_blocks: list[dict[str, Any]] = []
    for seg in segments:
        if seg["kind"] == "table":
            raw_blocks.append(
                {
                    "block_type": "table",
                    "text": seg["text"],
                    "start_line": seg["start_line"],
                    "end_line": seg["end_line"],
                }
            )
        else:
            raw_blocks.extend(_split_text_into_blocks(seg["text"], seg["start_line"]))

    blocks: list[dict[str, Any]] = []
    ordinal = 0
    for rb in raw_blocks:
        if rb["block_type"] == "noise":
            continue
        ordinal += 1
        start_line = int(rb["start_line"])
        chapter = _chapter_for_line(chapter_boundaries, start_line)
        # Prefer chapter boundary page; else approximate from lines
        split_idx = None
        # nearest boundary at or before this line with a page
        for b in chapter_boundaries:
            if b.get("line_no") is not None and int(b["line_no"]) <= start_line:
                if b.get("split_page_index") is not None:
                    split_idx = int(b["split_page_index"])
        if split_idx is None and page_count:
            split_idx = _map_line_to_split_page(
                start_line, total_lines=total_lines, page_count=page_count
            )
            page_method = "line_distribution_fallback"
            page_conf = 0.35
        else:
            page_method = "page_map" if split_idx is not None else "unknown"
            page_conf = 0.9 if split_idx is not None else 0.0

        source_pages, printed_labels, map_conf = _pages_from_page_map(split_idx, page_map)
        if source_pages:
            page_conf = max(page_conf, map_conf)

        text = str(rb["text"])
        btype = str(rb["block_type"])
        table_rows = None
        if btype == "table":
            parsed = parse_html_tables(text)
            table_rows = parsed[0] if parsed else []

        quality_flags: list[str] = []
        quality_status = "ready"
        if chapter["chapter_needs_review"] or chapter["chapter_assignment"] == "uncertain":
            quality_flags.append("low_confidence_chapter")
            quality_status = "needs_review"
        if page_method == "line_distribution_fallback":
            quality_flags.append("approx_page_mapping")
        if btype == "table" and not table_rows:
            quality_flags.append("table_parse_empty")
            quality_status = "needs_review"

        chunk_id = stable_chunk_id(
            document_version_id,
            block_type=btype,
            source_pdf_pages=source_pages,
            ordinal=ordinal,
            content=text,
        )
        block: dict[str, Any] = {
            "id": chunk_id,
            "document_version_id": document_version_id,
            "chapter_path": chapter["chapter_path"],
            "chapter_method": chapter["chapter_method"],
            "chapter_confidence": chapter["chapter_confidence"],
            "chapter_assignment": chapter["chapter_assignment"],
            "source_pdf_pages": source_pages,
            "printed_page_labels": printed_labels,
            "split_page_index": split_idx,
            "block_type": btype,
            "raw_text_ref": {
                "start_line": start_line,
                "end_line": int(rb["end_line"]),
                "split_page_index": split_idx,
                "source_pdf_pages": source_pages,
            },
            "cleaned_text": text,
            "quality_status": quality_status,
            "quality_flags": quality_flags,
            "pipeline_version": STRUCTURE_PIPELINE_VERSION,
            "page_mapping_method": page_method,
            "page_mapping_confidence": page_conf,
            "ordinal": ordinal,
            "book_template": book_template,
        }
        if table_rows is not None:
            block["table_rows"] = table_rows
            block["table_row_count"] = len(table_rows)
            block["table_col_count"] = max((len(r) for r in table_rows), default=0)
        if rb.get("heading"):
            block["heading"] = rb["heading"]
        blocks.append(block)
    return blocks


def build_page_records(
    page_map: list[dict[str, Any]],
    content_blocks: list[dict[str, Any]],
    *,
    document_version_id: str,
) -> list[dict[str, Any]]:
    """Assemble PageRecord list linked to ContentBlock ids."""
    by_split: dict[int, list[str]] = {}
    for b in content_blocks:
        idx = b.get("split_page_index")
        if idx is None:
            continue
        by_split.setdefault(int(idx), []).append(str(b["id"]))

    records: list[dict[str, Any]] = []
    for row in page_map:
        idx = int(row["split_page_index"])
        block_ids = by_split.get(idx, [])
        flags: list[str] = []
        status = "ready"
        if not block_ids:
            flags.append("no_content_blocks")
            status = "needs_review"
        if row.get("printed_page_label") in (None, ""):
            flags.append("missing_printed_label")
        records.append(
            {
                "document_version_id": document_version_id,
                "split_page_index": idx,
                "source_pdf_page_index": row.get("source_pdf_page_index"),
                "source_pdf_page_number": row.get("source_pdf_page_number"),
                "printed_page_label": row.get("printed_page_label"),
                "status": status,
                "quality_flags": flags,
                "content_block_ids": block_ids,
                "mapping_confidence": row.get("mapping_confidence"),
            }
        )
    return records


def default_structured_dir(source: Path) -> Path:
    """Map raw/cleaned source path to a sibling structured directory."""
    parts = list(source.parts)
    for marker in ("raw", "cleaned", "unzipped"):
        if marker in parts:
            idx = parts.index(marker)
            # drop unzipped segment from tail
            tail = [p for p in parts[idx + 1 :] if p != "unzipped"]
            # if source is a file, use parent as logical unit
            if source.is_file() or source.suffix:
                # remove filename from tail
                if tail and Path(tail[-1]).suffix:
                    tail = tail[:-1]
            new_parts = parts[:idx] + ["structured"] + tail
            return Path(*new_parts)
    if source.is_file():
        return source.parent / "structured"
    return source / "structured"


def structure_document(
    *,
    cleaned_md: str,
    document_version_id: str,
    content_list: list[dict[str, Any]] | None = None,
    page_map: list[dict[str, Any]] | None = None,
    book_template: str | None = None,
    source_pdf_page_start: int | None = None,
    expected_page_count: int | None = None,
) -> dict[str, Any]:
    """Run full structure stage: chapters, pages, content blocks."""
    from tools.document_pipeline.page_mapping import (
        build_page_map_from_content_list,
        page_map_coverage,
    )

    items = content_list or []
    if page_map is None:
        page_map = build_page_map_from_content_list(
            items,
            source_pdf_page_start=source_pdf_page_start,
            expected_page_count=expected_page_count,
        )
    md_headings = extract_markdown_headings(cleaned_md)
    cl_headings = extract_content_list_headings(items)
    chapters = build_chapter_tree(md_headings=md_headings, cl_headings=cl_headings)
    blocks = build_content_blocks(
        cleaned_md,
        document_version_id=document_version_id,
        chapter_boundaries=chapters,
        page_map=page_map,
        book_template=book_template,
    )
    pages = build_page_records(page_map, blocks, document_version_id=document_version_id)
    cov = page_map_coverage(page_map)
    low_conf_chapters = [c for c in chapters if c.get("needs_review")]
    uncertain_blocks = [b for b in blocks if b.get("chapter_assignment") == "uncertain"]

    return {
        "pipeline_version": STRUCTURE_PIPELINE_VERSION,
        "document_version_id": document_version_id,
        "book_template": book_template,
        "chapter_boundaries": chapters,
        "chapter_count": len([c for c in chapters if c.get("role") in ("chapter", "section")]),
        "low_confidence_chapter_count": len(low_conf_chapters),
        "page_records": pages,
        "content_blocks": blocks,
        "content_block_count": len(blocks),
        "page_map_coverage": cov,
        "metrics": {
            "heading_count": len(md_headings),
            "content_list_heading_count": len(cl_headings),
            "table_block_count": sum(1 for b in blocks if b["block_type"] == "table"),
            "paragraph_block_count": sum(1 for b in blocks if b["block_type"] == "paragraph"),
            "heading_block_count": sum(1 for b in blocks if b["block_type"] == "heading"),
            "needs_review_block_count": sum(
                1 for b in blocks if b.get("quality_status") == "needs_review"
            ),
            "uncertain_chapter_block_count": len(uncertain_blocks),
            "blocks_with_source_pages": sum(1 for b in blocks if b.get("source_pdf_pages")),
        },
        "input_sha256": sha256_bytes(cleaned_md.encode("utf-8")),
    }


def write_structured_artifacts(
    result: dict[str, Any],
    out_dir: Path,
    *,
    allow_raw_overwrite: bool = False,
) -> dict[str, Any]:
    """Write structured JSON artifacts outside raw trees."""
    if not allow_raw_overwrite:
        assert_not_raw_write_target(out_dir)
        if is_under_raw_tree(out_dir):
            raise RawError(f"structured output path is under raw tree: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    chapters_path = out_dir / "chapters.json"
    pages_path = out_dir / "pages.json"
    blocks_path = out_dir / "content_blocks.jsonl"
    summary_path = out_dir / "structure_summary.json"

    chapters_path.write_text(
        json.dumps(result["chapter_boundaries"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pages_path.write_text(
        json.dumps(result["page_records"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with blocks_path.open("w", encoding="utf-8") as fh:
        for block in result["content_blocks"]:
            fh.write(json.dumps(block, ensure_ascii=False) + "\n")

    summary = {
        k: v
        for k, v in result.items()
        if k not in ("chapter_boundaries", "page_records", "content_blocks")
    }
    summary.update(
        {
            "chapters_path": chapters_path.name,
            "pages_path": pages_path.name,
            "content_blocks_path": blocks_path.name,
            "chapters_sha256": sha256_file(chapters_path),
            "pages_sha256": sha256_file(pages_path),
            "content_blocks_sha256": sha256_file(blocks_path),
        }
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "out_dir": str(out_dir),
        "chapters": str(chapters_path),
        "pages": str(pages_path),
        "content_blocks": str(blocks_path),
        "summary": str(summary_path),
        **summary,
    }


def structure_result_dir(
    result_dir: Path,
    *,
    document_version_id: str | None = None,
    book_template: str | None = None,
    cleaned_md_path: Path | None = None,
    out_dir: Path | None = None,
    source_pdf_page_start: int | None = None,
    expected_page_count: int | None = None,
) -> dict[str, Any]:
    """Structure a MinerU sample/result directory (prefers cleaned markdown)."""
    result_dir = result_dir.expanduser().resolve()
    md_path, cl_path = find_md_and_content_list(result_dir)
    if cleaned_md_path is not None:
        md_path = cleaned_md_path
    else:
        # Prefer full.cleaned.md beside full.md
        if md_path is not None:
            cleaned_candidate = md_path.with_name("full.cleaned.md")
            if cleaned_candidate.is_file():
                md_path = cleaned_candidate
    if md_path is None or not md_path.is_file():
        raise RawError(f"markdown not found under {result_dir}")

    doc_id = document_version_id or result_dir.name
    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    items = load_content_list(cl_path)
    structured = structure_document(
        cleaned_md=md_text,
        document_version_id=doc_id,
        content_list=items,
        book_template=book_template,
        source_pdf_page_start=source_pdf_page_start,
        expected_page_count=expected_page_count,
    )
    dest = out_dir if out_dir is not None else default_structured_dir(md_path)
    written = write_structured_artifacts(structured, dest)
    return {**structured, **written, "source_md": str(md_path)}


__all__ = [
    "BOOK_TEMPLATE_KEYS",
    "BOOK_TEMPLATE_LABELS",
    "LOW_CHAPTER_CONFIDENCE",
    "STRUCTURE_PIPELINE_VERSION",
    "build_chapter_tree",
    "build_content_blocks",
    "build_page_records",
    "classify_heading",
    "default_structured_dir",
    "extract_content_list_headings",
    "extract_markdown_headings",
    "find_md_and_content_list",
    "load_content_list",
    "page_number",
    "stable_chunk_id",
    "structure_document",
    "structure_result_dir",
    "write_structured_artifacts",
]
