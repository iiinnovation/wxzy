"""Content-list / markdown location helpers used before full structure stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
