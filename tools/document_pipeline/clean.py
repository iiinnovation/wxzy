"""Deterministic OCR / header cleaning for MinerU markdown.

P3-T05: cleaned outputs never overwrite raw trees.
P3-T06: rule IDs, replace audit, page mapping helpers, clean.v2.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.document_pipeline.page_mapping import page_map_coverage
from tools.document_pipeline.raw import (
    RawError,
    assert_not_raw_write_target,
    file_fingerprint,
    is_under_raw_tree,
    sha256_bytes,
    sha256_file,
)

# ---------------------------------------------------------------------------
# Rule catalog (deterministic, no fact completion)
# ---------------------------------------------------------------------------

OCR_RULES: list[dict[str, str]] = [
    # Fangji / TCM OCR dictionary (known fixed errors only)
    {"rule_id": "ocr.fangji.jingmi", "from": "粳镶", "to": "粳米"},
    {"rule_id": "ocr.fangji.zhenzhen", "from": "黎黎", "to": "漐漐"},
    {"rule_id": "ocr.fangji.fuju", "from": "咬咀", "to": "㕮咀"},
    {"rule_id": "ocr.watermark.xueba_space", "from": "学朝 笔记", "to": "学霸 笔记"},
    {"rule_id": "ocr.watermark.xueba", "from": "学朝笔记", "to": "学霸笔记"},
    {"rule_id": "ocr.watermark.xueqi_space", "from": "学期 笔记", "to": "学霸 笔记"},
    {"rule_id": "ocr.watermark.xueqi", "from": "学期笔记", "to": "学霸笔记"},
    {"rule_id": "ocr.watermark.kaoyan_xueqi", "from": "中医考研 学期", "to": "中医考研 学霸"},
    {"rule_id": "ocr.watermark.kaoyan_xuechao", "from": "中医考研 学朝", "to": "中医考研 学霸"},
]

# Backward-compatible alias used by older imports/tests.
OCR_CORRECTIONS: list[tuple[str, str]] = [(r["from"], r["to"]) for r in OCR_RULES]

HEADER_NOISE_RULES: list[dict[str, str]] = [
    {
        "rule_id": "noise.header.kaoyan_note_md",
        "pattern": r"^##?\s*中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
    },
    {
        "rule_id": "noise.header.kaoyan_note",
        "pattern": r"^中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
    },
]

PAGE_NUMBER_RULES: list[dict[str, str]] = [
    {"rule_id": "noise.page_number.slash", "pattern": r"^/\s*\d{2,4}\s*$"},
    {"rule_id": "noise.page_number.bare", "pattern": r"^\d{2,4}\s*$"},
]

HEADER_NOISE_PATTERNS: list[str] = [r["pattern"] for r in HEADER_NOISE_RULES]
PAGE_NUMBER_PATTERNS: list[str] = [r["pattern"] for r in PAGE_NUMBER_RULES]

CLEAN_RULE_VERSION = "clean.v2"
BLANK_COLLAPSE_RULE_ID = "normalize.blank_lines.max2"


def _audit_entry(
    *,
    rule_id: str,
    before: str,
    after: str,
    count: int = 1,
    line_no: int | None = None,
    page: int | str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "rule_id": rule_id,
        "before": before,
        "after": after,
        "count": count,
    }
    if line_no is not None:
        entry["line_no"] = line_no
    if page is not None:
        entry["page"] = page
    return entry


def clean_markdown(md: str, *, page_hints: list[int | str | None] | None = None) -> dict[str, Any]:
    """Apply deterministic clean.v2 rules and return cleaned text + audit trail.

    ``page_hints`` is optional and reserved for future line→page alignment; when
    omitted, replacement audit records leave ``page`` unset (not fabricated).
    """
    del page_hints  # reserved; pure md cleaning does not invent page numbers
    original = md
    replacements: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []

    for rule in OCR_RULES:
        bad, good, rule_id = rule["from"], rule["to"], rule["rule_id"]
        count = md.count(bad)
        if count:
            md = md.replace(bad, good)
            entry = _audit_entry(rule_id=rule_id, before=bad, after=good, count=count)
            replacements.append(entry)
            corrections.append(
                {
                    "rule_id": rule_id,
                    "from": bad,
                    "to": good,
                    "count": count,
                }
            )

    removed_headers: list[str] = []
    removed_page_numbers: list[str] = []
    kept_lines: list[str] = []
    header_pats = [(r["rule_id"], re.compile(r["pattern"])) for r in HEADER_NOISE_RULES]
    page_pats = [(r["rule_id"], re.compile(r["pattern"])) for r in PAGE_NUMBER_RULES]

    for line_no, line in enumerate(md.splitlines(), start=1):
        stripped = line.strip()
        matched = False
        for rule_id, pat in header_pats:
            if pat.match(stripped):
                removed_headers.append(stripped)
                replacements.append(
                    _audit_entry(
                        rule_id=rule_id,
                        before=stripped,
                        after="",
                        count=1,
                        line_no=line_no,
                    )
                )
                matched = True
                break
        if not matched:
            for rule_id, pat in page_pats:
                if pat.match(stripped) and len(stripped) <= 6:
                    removed_page_numbers.append(stripped)
                    replacements.append(
                        _audit_entry(
                            rule_id=rule_id,
                            before=stripped,
                            after="",
                            count=1,
                            line_no=line_no,
                        )
                    )
                    matched = True
                    break
        if not matched:
            kept_lines.append(line)

    cleaned_lines: list[str] = []
    blank = 0
    blank_collapsed = 0
    for line in kept_lines:
        if not line.strip():
            blank += 1
            if blank <= 2:
                cleaned_lines.append(line)
            else:
                blank_collapsed += 1
        else:
            blank = 0
            cleaned_lines.append(line)
    if blank_collapsed:
        replacements.append(
            _audit_entry(
                rule_id=BLANK_COLLAPSE_RULE_ID,
                before="\\n{3,}",
                after="\\n\\n",
                count=blank_collapsed,
            )
        )

    cleaned = "\n".join(cleaned_lines).strip() + "\n"

    return {
        "cleaned_md": cleaned,
        "original_chars": len(original),
        "cleaned_chars": len(cleaned),
        "corrections": corrections,
        "replacements": replacements,
        "removed_headers": removed_headers,
        "removed_page_numbers": removed_page_numbers,
        "removed_header_count": len(removed_headers),
        "removed_page_number_count": len(removed_page_numbers),
        "rule_version": CLEAN_RULE_VERSION,
        "rule_ids_applied": sorted({r["rule_id"] for r in replacements}),
        "input_sha256": sha256_bytes(original.encode("utf-8")),
        "output_sha256": sha256_bytes(cleaned.encode("utf-8")),
    }


def default_cleaned_path(source: Path) -> Path:
    """Map a raw markdown path to a sibling cleaned path outside raw trees.

    raw/.../unzipped/full.md -> cleaned/.../full.cleaned.md (unzipped segment dropped)
    """
    parts = list(source.parts)
    if "raw" in parts:
        idx = parts.index("raw")
        tail = [p for p in parts[idx + 1 :] if p != "unzipped"]
        new_parts = parts[:idx] + ["cleaned"] + tail
        candidate = Path(*new_parts)
        if candidate.name == "full.md":
            candidate = candidate.with_name("full.cleaned.md")
        elif candidate.suffix == ".md":
            candidate = candidate.with_name(candidate.stem + ".cleaned.md")
        return candidate
    if source.name == "full.md":
        return source.with_name("full.cleaned.md")
    return source.with_name(source.stem + ".cleaned.md")


def write_cleaned_markdown(
    source: Path,
    *,
    out: Path | None = None,
    allow_raw_overwrite: bool = False,
    page_map: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Clean markdown from source and write to a non-raw destination.

    Records input/output hashes and replace audit. Never mutates the source file.
    When ``page_map`` is provided, writes a sidecar ``*.page_map.json`` next to
    the cleaned markdown.
    """
    if not source.is_file():
        raise RawError(f"source markdown not found: {source}")

    source_fp = file_fingerprint(source)
    raw_text = source.read_text(encoding="utf-8", errors="replace")
    info = clean_markdown(raw_text)

    dest = out if out is not None else default_cleaned_path(source)
    if not allow_raw_overwrite:
        assert_not_raw_write_target(dest)
        if dest.resolve() == source.resolve():
            raise RawError("cleaned output must not overwrite the source raw file")
        if is_under_raw_tree(dest):
            raise RawError(f"cleaned output path is under raw tree: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(info["cleaned_md"], encoding="utf-8")
    meta = {k: v for k, v in info.items() if k != "cleaned_md"}
    meta.update(
        {
            "source_path": source.name,
            "source_sha256": source_fp["sha256"],
            "source_size_bytes": source_fp["size_bytes"],
            "source_mtime_ns": source_fp["mtime_ns"],
            "output_path": dest.name,
            "output_sha256": sha256_file(dest),
            "rule_version": CLEAN_RULE_VERSION,
        }
    )
    meta_path = dest.with_suffix(dest.suffix + ".meta.json")
    if not allow_raw_overwrite:
        assert_not_raw_write_target(meta_path)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    page_map_path: Path | None = None
    if page_map is not None:
        page_map_path = dest.with_suffix(dest.suffix + ".page_map.json")
        if not allow_raw_overwrite:
            assert_not_raw_write_target(page_map_path)
        payload = {
            "rule_version": CLEAN_RULE_VERSION,
            "source_path": source.name,
            "page_map": page_map,
            "coverage": page_map_coverage(page_map),
        }
        page_map_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        meta["page_map_path"] = page_map_path.name
        meta["page_map_coverage"] = payload["coverage"]
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    after = file_fingerprint(source)
    if after != source_fp:
        raise RawError("raw source changed during clean; refusing to trust outputs")

    return {
        **meta,
        "source": str(source),
        "out": str(dest),
        "meta": str(meta_path),
        "page_map_file": str(page_map_path) if page_map_path else None,
        "source_fingerprint_before": source_fp,
        "source_fingerprint_after": after,
        "raw_unchanged": after == source_fp,
    }


__all__ = [
    "BLANK_COLLAPSE_RULE_ID",
    "CLEAN_RULE_VERSION",
    "HEADER_NOISE_PATTERNS",
    "HEADER_NOISE_RULES",
    "OCR_CORRECTIONS",
    "OCR_RULES",
    "PAGE_NUMBER_PATTERNS",
    "PAGE_NUMBER_RULES",
    "clean_markdown",
    "default_cleaned_path",
    "write_cleaned_markdown",
]
