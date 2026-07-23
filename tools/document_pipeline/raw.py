"""Raw MinerU artifact helpers (zip unpack + result directory summary).

Full zip-slip hardening lands in P3-T05; this module preserves current
behavior for CLI compatibility and adds a basic path-safety check used by tests.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


def is_safe_zip_member(name: str) -> bool:
    """Reject absolute paths and parent-directory traversal in zip entries."""
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    # Windows drive-style absolute paths
    if len(name) >= 2 and name[1] == ":":
        return False
    parts = Path(name).parts
    if any(part == ".." for part in parts):
        return False
    return True


def unpack_zip(zip_path: Path, dest: Path, *, enforce_safe_members: bool = False) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if enforce_safe_members and not is_safe_zip_member(info.filename):
                raise ValueError(f"unsafe zip member path: {info.filename!r}")
        zf.extractall(dest)
        names = zf.namelist()
    return names


def summarize_result_dir(result_dir: Path) -> dict[str, Any]:
    files = sorted(
        p.relative_to(result_dir).as_posix() for p in result_dir.rglob("*") if p.is_file()
    )
    md_files = list(result_dir.rglob("*.md"))
    content_lists = list(result_dir.rglob("*content_list.json"))
    summary: dict[str, Any] = {
        "file_count": len(files),
        "files": files[:100],
        "markdown_chars": 0,
        "markdown_preview": "",
        "content_list_items": 0,
        "page_indexes_seen": [],
        "types_count": {},
    }
    if md_files:
        md = md_files[0].read_text(encoding="utf-8", errors="replace")
        summary["markdown_chars"] = len(md)
        summary["markdown_preview"] = md[:1200]
        summary["markdown_path"] = str(md_files[0].relative_to(result_dir))
    if content_lists:
        raw = json.loads(content_lists[0].read_text(encoding="utf-8", errors="replace"))
        items = (
            raw if isinstance(raw, list) else raw.get("pdf_info") or raw.get("content_list") or []
        )
        if isinstance(items, list):
            summary["content_list_items"] = len(items)
            pages: set[Any] = set()
            types: dict[str, int] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = str(it.get("type") or it.get("category") or "unknown")
                types[t] = types.get(t, 0) + 1
                for k in ("page_idx", "page_no", "page", "page_index"):
                    if k in it and it[k] is not None:
                        pages.add(it[k])
            summary["types_count"] = dict(sorted(types.items(), key=lambda x: (-x[1], x[0])))
            summary["page_indexes_seen"] = sorted(pages)[:50]
            summary["content_list_path"] = str(content_lists[0].relative_to(result_dir))
    return summary
