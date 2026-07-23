"""Deterministic OCR / header cleaning for MinerU markdown."""

from __future__ import annotations

import re
from typing import Any

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
    }
