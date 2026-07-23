"""Deterministic OCR / header cleaning for MinerU markdown.

P3-T05: cleaned outputs never overwrite raw trees. Write to a separate
cleaned path and record input/output hashes for audit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.document_pipeline.raw import (
    RawError,
    assert_not_raw_write_target,
    file_fingerprint,
    is_under_raw_tree,
    sha256_bytes,
    sha256_file,
)

OCR_CORRECTIONS: list[tuple[str, str]] = [
    ("粳镶", "粳米"),
    ("黎黎", "漐漐"),
    ("咬咀", "㕮咀"),
    ("学朝 笔记", "学霸 笔记"),
    ("学朝笔记", "学霸笔记"),
    ("学期 笔记", "学霸 笔记"),
    ("学期笔记", "学霸笔记"),
    ("中医考研 学期", "中医考研 学霸"),
    ("中医考研 学朝", "中医考研 学霸"),
]

HEADER_NOISE_PATTERNS: list[str] = [
    r"^##?\s*中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
    r"^中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
]

PAGE_NUMBER_PATTERNS: list[str] = [
    r"^/\s*\d{2,4}\s*$",
    r"^\d{2,4}\s*$",
]

CLEAN_RULE_VERSION = "clean.v1"


def clean_markdown(md: str) -> dict[str, Any]:
    original = md
    corrections: list[dict[str, Any]] = []
    for bad, good in OCR_CORRECTIONS:
        count = md.count(bad)
        if count:
            md = md.replace(bad, good)
            corrections.append({"from": bad, "to": good, "count": count})

    removed_headers: list[str] = []
    removed_page_numbers: list[str] = []
    kept_lines: list[str] = []
    for line in md.splitlines():
        stripped = line.strip()
        is_noise = False
        for pat in HEADER_NOISE_PATTERNS:
            if re.match(pat, stripped):
                removed_headers.append(stripped)
                is_noise = True
                break
        if not is_noise:
            for pat in PAGE_NUMBER_PATTERNS:
                if re.match(pat, stripped) and len(stripped) <= 6:
                    removed_page_numbers.append(stripped)
                    is_noise = True
                    break
        if not is_noise:
            kept_lines.append(line)

    cleaned_lines: list[str] = []
    blank = 0
    for line in kept_lines:
        if not line.strip():
            blank += 1
            if blank <= 2:
                cleaned_lines.append(line)
        else:
            blank = 0
            cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip() + "\n"

    return {
        "cleaned_md": cleaned,
        "original_chars": len(original),
        "cleaned_chars": len(cleaned),
        "corrections": corrections,
        "removed_headers": removed_headers,
        "removed_page_numbers": removed_page_numbers,
        "removed_header_count": len(removed_headers),
        "removed_page_number_count": len(removed_page_numbers),
        "rule_version": CLEAN_RULE_VERSION,
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
) -> dict[str, Any]:
    """Clean markdown from source and write to a non-raw destination.

    Records input/output hashes. Never mutates the source file.
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

    # Re-check source unchanged (immutability guarantee for callers/tests).
    after = file_fingerprint(source)
    if after != source_fp:
        raise RawError("raw source changed during clean; refusing to trust outputs")

    return {
        **meta,
        "source": str(source),
        "out": str(dest),
        "meta": str(meta_path),
        "source_fingerprint_before": source_fp,
        "source_fingerprint_after": after,
        "raw_unchanged": after == source_fp,
    }


__all__ = [
    "CLEAN_RULE_VERSION",
    "OCR_CORRECTIONS",
    "clean_markdown",
    "default_cleaned_path",
    "write_cleaned_markdown",
]
