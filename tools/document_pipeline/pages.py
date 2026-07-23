"""Page-range parsing utilities (1-based inclusive user specs)."""

from __future__ import annotations


def parse_pages(spec: str) -> list[int]:
    """Parse specs like ``5-6,20,40-41`` into ordered unique 1-based pages."""
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if end < start:
                raise SystemExit(f"invalid page range: {part}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    seen: set[int] = set()
    out: list[int] = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            out.append(p)
    if not out:
        raise SystemExit("no pages selected")
    return out
