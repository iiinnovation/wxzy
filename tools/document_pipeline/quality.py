"""Document quality report and gate for MinerU result directories.

P3-T08: page coverage, empty pages, garbled text, tables, chapters,
suspicious OCR, mapping, and terminal status. Summaries must not embed
full source markdown.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.clean import OCR_RULES, clean_markdown
from tools.document_pipeline.generation import parse_html_tables
from tools.document_pipeline.page_mapping import (
    build_page_map_from_content_list,
    page_map_coverage,
)
from tools.document_pipeline.structure import (
    find_md_and_content_list,
    load_content_list,
    page_number,
)

QUALITY_PIPELINE_VERSION = "quality.v1"

# Residual OCR / watermark tokens that must not remain in gate-ready text.
# Patterns intentionally include known-fixed OCR forms (pre-clean residuals).
SUSPICIOUS_OCR_PATTERNS: dict[str, str] = {
    "学朝": r"学朝",
    "学期笔记": r"学期\s*笔记",
    "粳镶": r"粳镶",
    "咬咀": r"咬咀",
    "黎黎": r"黎黎",
}

# Soft markers (warnings only unless combined with other failures).
SOFT_SUSPICIOUS_PATTERNS: dict[str, str] = {
    "slash_page_in_md": r"(?m)^/\s*\d{2,4}\s*$",
}

# Replacement-character / extreme garble heuristics.
GARBLE_REPLACEMENT_RE = re.compile(r"[\uFFFD\u25A1\u25A0\u25CB\u25CF]{2,}|�{2,}")
# CJK unified ideographs + common fullwidth punctuation range for ratio checks.
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

MIN_MARKDOWN_CHARS = 80
EMPTY_PAGE_MAX_CHARS = 8
CONTEXT_RADIUS = 24
MAX_CONTEXT_LEN = 80
MAX_HITS_PER_PATTERN = 5
MAX_ISSUE_SAMPLES = 20
MAX_TABLE_SAMPLE_LEN = 120
MAX_HEADING_PREVIEW = 12
MAX_HEADING_LEN = 80


def _short_context(text: str, start: int, end: int) -> str:
    """Return a short, single-line context snippet (never full document body)."""
    lo = max(0, start - CONTEXT_RADIUS)
    hi = min(len(text), end + CONTEXT_RADIUS)
    ctx = text[lo:hi].replace("\n", " ").replace("\r", " ").strip()
    if len(ctx) > MAX_CONTEXT_LEN:
        ctx = ctx[: MAX_CONTEXT_LEN - 1] + "…"
    return ctx


def _item_text(it: dict[str, Any]) -> str:
    text = it.get("text") or it.get("content") or it.get("table_body") or ""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    return str(text)


def _chars_on_page(items: list[dict[str, Any]], page_idx: int) -> int:
    total = 0
    for it in items:
        if page_number(it.get("page_idx")) != page_idx:
            continue
        t = str(it.get("type") or "")
        if t in ("page_number", "header", "footer", "aside_text"):
            continue
        total += len(_item_text(it).strip())
    return total


def _table_is_bad(html: str) -> tuple[bool, str]:
    """Return (is_bad, reason_code) for one HTML table fragment."""
    stripped = html.strip()
    if not stripped or re.fullmatch(r"<table[^>]*>\s*</table>", stripped, flags=re.I):
        return True, "empty_table"
    parsed = parse_html_tables(html)
    if not parsed:
        return True, "unparseable_table"
    rows = parsed[0]
    if not rows:
        return True, "empty_table"
    non_empty_cells = sum(1 for row in rows for cell in row if str(cell).strip())
    if non_empty_cells == 0:
        return True, "empty_table_cells"
    return False, ""


def _garbled_segments(md: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for m in GARBLE_REPLACEMENT_RE.finditer(md):
        hits.append(
            {
                "code": "replacement_chars",
                "context": _short_context(md, m.start(), m.end()),
            }
        )
        if len(hits) >= MAX_ISSUE_SAMPLES:
            break

    # Extreme non-CJK ratio on long CJK-target documents.
    sample = md[:8000]
    cjk = len(CJK_RE.findall(sample))
    latin = len(LATIN_RE.findall(sample))
    alnum_like = cjk + latin
    if alnum_like >= 200 and cjk / alnum_like < 0.15 and latin / alnum_like > 0.6:
        hits.append(
            {
                "code": "extreme_non_cjk_ratio",
                "context": f"cjk={cjk} latin={latin} ratio={cjk / alnum_like:.3f}",
            }
        )
    return hits


def _scan_patterns(md: str, patterns: dict[str, str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for name, pat in patterns.items():
        count_for = 0
        for m in re.finditer(pat, md):
            hits.append(
                {
                    "pattern": name,
                    "context": _short_context(md, m.start(), m.end()),
                }
            )
            count_for += 1
            if count_for >= MAX_HITS_PER_PATTERN:
                break
    return hits


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "fail",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": severity,
    }
    if detail:
        row["detail"] = detail
    return row


def _terminal_status(
    *,
    fail_issues: list[dict[str, Any]],
    review_issues: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    if fail_issues:
        return "fail"
    if review_issues or warnings:
        return "needs_review"
    return "pass"


def quality_report_for_dir(
    result_dir: Path,
    sample_key: str | None = None,
    *,
    expected_pages: int | None = None,
    source_pdf_page_start: int | None = None,
    gate: bool = True,
) -> dict[str, Any]:
    """Build a quality report for one MinerU sample directory.

    When ``gate`` is True (default), residual suspicious OCR and bad tables are
    hard failures. Summaries never include full source markdown.
    """
    md_path, cl_path = find_md_and_content_list(result_dir)
    report: dict[str, Any] = {
        "pipeline_version": QUALITY_PIPELINE_VERSION,
        "sample": sample_key or result_dir.name,
        "result_dir": str(result_dir),
        "markdown_path": str(md_path) if md_path else None,
        "content_list_path": str(cl_path) if cl_path else None,
        "ok": False,
        "gate_ok": False,
        "terminal_status": "fail",
        "exit_code": 1,
        "issues": [],  # human strings (compat)
        "issue_records": [],  # structured
        "warnings": [],
        "metrics": {},
        "suspicious_hits": [],
        "page_mapping_preview": [],
        "headings": [],
        "tables": {"html_count": 0, "pipe_md_count": 0, "bad_count": 0, "samples": []},
        "cleaning_preview": {},
        "page_coverage": {},
        "page_map_coverage": {},
        "empty_pages": [],
        "garble_hits": [],
        "chapter_summary": {},
    }

    issue_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    if md_path is None:
        rec = _issue("missing_markdown", "missing full.md / markdown")
        issue_records.append(rec)
        report["issues"] = [rec["message"]]
        report["issue_records"] = issue_records
        report["terminal_status"] = "fail"
        report["exit_code"] = 1
        report["ok"] = False
        report["gate_ok"] = False
        report["recommendation"] = "FAIL"
        return report

    md = md_path.read_text(encoding="utf-8", errors="replace")
    items = load_content_list(cl_path)
    types = Counter(str(it.get("type") or "unknown") for it in items)
    pages_seen = sorted(
        {p for it in items if (p := page_number(it.get("page_idx"))) is not None and p >= 0}
    )

    page_numbers: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    for it in items:
        t = str(it.get("type") or "")
        text = _item_text(it)
        if t == "page_number":
            page_numbers.append(
                {
                    "page_idx": it.get("page_idx"),
                    "text": text[:40],
                }
            )
        elif t in ("header", "aside_text"):
            headers.append(
                {
                    "type": t,
                    "page_idx": it.get("page_idx"),
                    "text": text[:80],
                }
            )

    hard_hits = _scan_patterns(md, SUSPICIOUS_OCR_PATTERNS)
    soft_hits = _scan_patterns(md, SOFT_SUSPICIOUS_PATTERNS)
    hits = hard_hits + soft_hits

    html_tables = re.findall(r"<table[\s\S]*?</table>", md, flags=re.I)
    pipe_tables = re.findall(r"(?m)^\|.+\|$", md)
    headings_raw = re.findall(r"(?m)^#{1,6}\s+.+", md)
    headings = [h[:MAX_HEADING_LEN] for h in headings_raw[:MAX_HEADING_PREVIEW]]

    bad_tables: list[dict[str, Any]] = []
    table_samples: list[str] = []
    for idx, table_html in enumerate(html_tables):
        is_bad, reason = _table_is_bad(table_html)
        sample = re.sub(r"\s+", " ", table_html)[:MAX_TABLE_SAMPLE_LEN]
        if len(table_samples) < 3:
            table_samples.append(sample)
        if is_bad:
            bad_tables.append(
                {
                    "index": idx,
                    "reason": reason,
                    "sample": sample,
                }
            )

    dose_lines: list[str] = []
    for line in md.splitlines():
        if re.search(r"[钱两分升合斤枚]", line) and len(line) < 160:
            if any(k in line for k in ("组成", "用法", "钱", "两", "分", "升", "合", "斤", "枚")):
                dose_lines.append(line[:120])
            if len(dose_lines) >= 8:
                break

    clean_info = clean_markdown(md)
    residual_after_clean = _scan_patterns(clean_info["cleaned_md"], SUSPICIOUS_OCR_PATTERNS)
    report["cleaning_preview"] = {
        "rule_version": clean_info.get("rule_version"),
        "rule_ids_applied": clean_info.get("rule_ids_applied") or [],
        "corrections": clean_info["corrections"][:20],
        "replacement_count": len(clean_info.get("replacements") or []),
        "removed_header_count": clean_info["removed_header_count"],
        "removed_page_number_count": clean_info["removed_page_number_count"],
        "removed_headers": [str(h)[:80] for h in (clean_info.get("removed_headers") or [])[:10]],
        "char_delta": clean_info["original_chars"] - clean_info["cleaned_chars"],
        "residual_suspicious_after_clean": len(residual_after_clean),
    }

    # Page coverage: expected range from arg, else from min/max page_idx.
    missing_pages: list[int] = []
    if expected_pages is not None and expected_pages > 0:
        expected_set = set(range(expected_pages))
        seen_set = set(pages_seen)
        missing_pages = sorted(expected_set - seen_set)
        coverage_complete = not missing_pages and len(pages_seen) > 0
        page_span = expected_pages
    elif pages_seen:
        lo, hi = min(pages_seen), max(pages_seen)
        expected_set = set(range(lo, hi + 1))
        missing_pages = sorted(expected_set - set(pages_seen))
        coverage_complete = not missing_pages
        page_span = hi - lo + 1
    else:
        coverage_complete = False
        page_span = 0

    empty_pages: list[int] = []
    if pages_seen or (expected_pages and expected_pages > 0):
        check_pages = (
            list(range(expected_pages)) if expected_pages and expected_pages > 0 else pages_seen
        )
        for p in check_pages:
            if p in missing_pages:
                continue
            if _chars_on_page(items, p) <= EMPTY_PAGE_MAX_CHARS:
                empty_pages.append(p)

    garble_hits = _garbled_segments(md)

    page_map = build_page_map_from_content_list(
        items,
        source_pdf_page_start=source_pdf_page_start,
        expected_page_count=expected_pages,
    )
    map_cov = page_map_coverage(page_map)

    chapter_headings = [
        h for h in headings_raw if re.search(r"第.+[章节]|第[一二三四五六七八九十百千\d]+", h)
    ]
    chapter_summary = {
        "heading_count": len(headings_raw),
        "chapter_like_heading_count": len(chapter_headings),
        "has_chapter_signal": bool(chapter_headings)
        or any("章" in h or "节" in h for h in headings_raw),
    }

    metrics = {
        "markdown_chars": len(md),
        "markdown_lines": md.count("\n") + 1,
        "content_list_items": len(items),
        "types_count": dict(types),
        "pages_seen": pages_seen,
        "page_count_est": len(pages_seen),
        "page_span": page_span,
        "expected_pages": expected_pages,
        "missing_page_count": len(missing_pages),
        "empty_page_count": len(empty_pages),
        "heading_count": len(headings_raw),
        "html_table_count": len(html_tables),
        "pipe_table_count": len(pipe_tables),
        "bad_table_count": len(bad_tables),
        "page_number_items": len(page_numbers),
        "header_aside_items": len(headers),
        "suspicious_hit_count": len(hits),
        "hard_suspicious_hit_count": len(hard_hits),
        "garble_hit_count": len(garble_hits),
        "known_ocr_rule_count": len(OCR_RULES),
    }
    report["metrics"] = metrics
    report["suspicious_hits"] = hits[:50]
    report["garble_hits"] = garble_hits[:MAX_ISSUE_SAMPLES]
    report["headings"] = headings
    report["tables"] = {
        "html_count": len(html_tables),
        "pipe_md_count": len(pipe_tables),
        "bad_count": len(bad_tables),
        "bad": bad_tables[:MAX_ISSUE_SAMPLES],
        "samples": table_samples,
    }
    report["page_mapping_preview"] = page_numbers[:20]
    report["header_noise_preview"] = headers[:15]
    report["dose_line_preview"] = dose_lines
    report["page_coverage"] = {
        "pages_seen": pages_seen,
        "missing_pages": missing_pages,
        "empty_pages": empty_pages,
        "complete": coverage_complete,
        "expected_pages": expected_pages,
    }
    report["page_map_coverage"] = map_cov
    report["empty_pages"] = empty_pages
    report["chapter_summary"] = chapter_summary

    # ---- gate issues ----
    if not pages_seen:
        issue_records.append(_issue("no_page_idx", "content_list has no page_idx"))
    if missing_pages:
        issue_records.append(
            _issue(
                "missing_pages",
                f"missing page_idx values: {missing_pages}",
                detail={"missing_pages": missing_pages},
            )
        )
    elif pages_seen and pages_seen != list(range(min(pages_seen), max(pages_seen) + 1)):
        # Contiguity already covered by missing_pages; keep warning for unexpected order only.
        warnings.append(f"page_idx not contiguous: {pages_seen}")

    if len(md) < MIN_MARKDOWN_CHARS:
        issue_records.append(
            _issue(
                "markdown_too_short",
                f"markdown too short ({len(md)} < {MIN_MARKDOWN_CHARS})",
            )
        )

    if empty_pages:
        issue_records.append(
            _issue(
                "empty_pages",
                f"empty or near-empty pages: {empty_pages}",
                severity="needs_review",
                detail={"empty_pages": empty_pages},
            )
        )

    if garble_hits:
        issue_records.append(
            _issue(
                "garbled_text",
                f"garbled text signals: {len(garble_hits)}",
                detail={"samples": garble_hits[:5]},
            )
        )

    if bad_tables:
        issue_records.append(
            _issue(
                "bad_tables",
                f"bad or empty tables: {len(bad_tables)}",
                detail={"bad": bad_tables[:5]},
            )
        )

    # Residual hard suspicious OCR fails the gate. Prefer residual-after-clean
    # when clean fixes known dictionary entries; otherwise fail on source hits.
    if residual_after_clean:
        issue_records.append(
            _issue(
                "suspicious_ocr",
                f"residual suspicious OCR after clean: {len(residual_after_clean)}",
                detail={"hits": residual_after_clean[:10]},
            )
        )
    elif hard_hits and gate:
        # Source still contains known bad tokens (clean would fix some, but gate
        # on raw result directories should surface them). Fail so fixtures fail
        # before optional clean step.
        issue_records.append(
            _issue(
                "suspicious_ocr",
                f"suspicious OCR patterns in source: {len(hard_hits)}",
                detail={"hits": hard_hits[:10]},
            )
        )

    if expected_pages is not None and expected_pages > 0 and not map_cov.get("complete"):
        issue_records.append(
            _issue(
                "mapping_incomplete",
                "page map coverage incomplete for expected pages",
                detail={"page_map_coverage": map_cov},
            )
        )
    elif pages_seen and not map_cov.get("complete") and source_pdf_page_start is not None:
        issue_records.append(
            _issue(
                "mapping_incomplete",
                "page map coverage incomplete",
                severity="needs_review",
                detail={"page_map_coverage": map_cov},
            )
        )

    if not chapter_summary["has_chapter_signal"] and len(md) >= MIN_MARKDOWN_CHARS:
        warnings.append("no chapter/section heading signal detected")

    if metrics["html_table_count"] == 0 and metrics["pipe_table_count"] == 0:
        warnings.append("no tables detected; may be fine for prose-only pages")

    if any("学朝" in h or "学期" in h for h in headings_raw):
        warnings.append("header watermark leaked into markdown headings")

    if soft_hits:
        warnings.append(f"found {len(soft_hits)} soft suspicious markers (slash page lines, etc.)")

    # Partition severity
    fail_issues = [r for r in issue_records if r.get("severity") == "fail"]
    review_issues = [r for r in issue_records if r.get("severity") == "needs_review"]

    # empty_pages alone is needs_review, not hard fail, unless also missing content.
    # Gate fails on any severity=fail issue.
    terminal = _terminal_status(
        fail_issues=fail_issues,
        review_issues=review_issues,
        warnings=warnings,
    )
    # empty_pages currently needs_review — if only those and no fail, terminal is needs_review
    gate_ok = len(fail_issues) == 0
    # For CLI gate: needs_review still exits non-zero so CI blocks publication path.
    exit_code = 0 if (gate_ok and terminal == "pass") else 1

    report["issue_records"] = issue_records
    report["issues"] = [r["message"] for r in issue_records]
    report["warnings"] = warnings
    report["ok"] = gate_ok and terminal == "pass"
    report["gate_ok"] = gate_ok
    report["terminal_status"] = terminal
    report["exit_code"] = exit_code
    report["recommendation"] = {
        "pass": "PASS",
        "needs_review": "NEEDS_HUMAN_REVIEW",
        "fail": "FAIL",
    }[terminal]
    report["summary"] = build_report_summary(report)
    return report


def build_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Compact summary suitable for tracked artifacts (no full source text)."""
    m = report.get("metrics") or {}
    return {
        "sample": report.get("sample"),
        "terminal_status": report.get("terminal_status"),
        "ok": report.get("ok"),
        "gate_ok": report.get("gate_ok"),
        "exit_code": report.get("exit_code"),
        "issue_codes": [r.get("code") for r in (report.get("issue_records") or [])],
        "warning_count": len(report.get("warnings") or []),
        "metrics": {
            "markdown_chars": m.get("markdown_chars"),
            "page_count_est": m.get("page_count_est"),
            "missing_page_count": m.get("missing_page_count"),
            "empty_page_count": m.get("empty_page_count"),
            "html_table_count": m.get("html_table_count"),
            "bad_table_count": m.get("bad_table_count"),
            "heading_count": m.get("heading_count"),
            "hard_suspicious_hit_count": m.get("hard_suspicious_hit_count"),
            "garble_hit_count": m.get("garble_hit_count"),
        },
        "page_map_coverage": {
            "complete": (report.get("page_map_coverage") or {}).get("complete"),
            "pdf_coverage": (report.get("page_map_coverage") or {}).get("pdf_coverage"),
            "printed_coverage": (report.get("page_map_coverage") or {}).get("printed_coverage"),
        },
        "chapter_summary": report.get("chapter_summary") or {},
    }


def aggregate_gate_result(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multi-sample gate result for CLI exit codes."""
    statuses = Counter(str(r.get("terminal_status") or "fail") for r in reports)
    any_fail = any(r.get("terminal_status") == "fail" for r in reports)
    any_review = any(r.get("terminal_status") == "needs_review" for r in reports)
    all_pass = bool(reports) and all(r.get("terminal_status") == "pass" for r in reports)
    exit_code = 0 if all_pass else 1
    return {
        "samples": len(reports),
        "status_counts": dict(statuses),
        "all_pass": all_pass,
        "any_fail": any_fail,
        "any_needs_review": any_review,
        "exit_code": exit_code,
        "ok_by_sample": {r.get("sample"): r.get("ok") for r in reports},
        "terminal_by_sample": {r.get("sample"): r.get("terminal_status") for r in reports},
        "summaries": [r.get("summary") or build_report_summary(r) for r in reports],
    }


def write_quality_markdown(reports: list[dict[str, Any]], out_path: Path) -> None:
    """Write a human-readable summary without embedding full source text."""
    lines: list[str] = []
    lines.append("# Document quality report")
    lines.append("")
    lines.append(f"- generated_at: `{datetime.now(UTC).isoformat()}`")
    lines.append(f"- pipeline_version: `{QUALITY_PIPELINE_VERSION}`")
    lines.append(f"- samples: {len(reports)}")
    agg = aggregate_gate_result(reports)
    lines.append(f"- aggregate_exit_code: `{agg['exit_code']}`")
    lines.append(f"- status_counts: `{agg['status_counts']}`")
    lines.append("")

    for r in reports:
        m = r.get("metrics") or {}
        pc = r.get("page_coverage") or {}
        cov = r.get("page_map_coverage") or {}
        lines.append(f"## {r.get('sample')}")
        lines.append("")
        lines.append(f"- terminal_status: `{r.get('terminal_status')}`")
        lines.append(f"- ok: `{r.get('ok')}`")
        lines.append(f"- gate_ok: `{r.get('gate_ok')}`")
        lines.append(f"- recommendation: `{r.get('recommendation')}`")
        lines.append(f"- markdown_chars: `{m.get('markdown_chars')}`")
        lines.append(f"- content_list_items: `{m.get('content_list_items')}`")
        lines.append(f"- pages_seen: `{m.get('pages_seen')}`")
        lines.append(f"- missing_pages: `{pc.get('missing_pages')}`")
        lines.append(f"- empty_pages: `{pc.get('empty_pages')}`")
        lines.append(f"- page_map_complete: `{cov.get('complete')}`")
        lines.append(
            f"- page_map pdf/printed coverage: "
            f"`{cov.get('pdf_coverage')}` / `{cov.get('printed_coverage')}`"
        )
        lines.append(f"- types: `{m.get('types_count')}`")
        lines.append(
            f"- tables html/pipe/bad: "
            f"`{m.get('html_table_count')}` / `{m.get('pipe_table_count')}` / "
            f"`{m.get('bad_table_count')}`"
        )
        lines.append(f"- headings: `{m.get('heading_count')}`")
        lines.append(f"- hard_suspicious_hits: `{m.get('hard_suspicious_hit_count')}`")
        lines.append(f"- garble_hits: `{m.get('garble_hit_count')}`")
        cp = r.get("cleaning_preview") or {}
        lines.append(
            f"- cleaning corrections: `{cp.get('corrections') and len(cp.get('corrections') or [])}`"
        )
        lines.append(f"- removed header noise: `{cp.get('removed_header_count')}`")

        if r.get("issue_records"):
            lines.append("- issues:")
            for rec in r["issue_records"]:
                lines.append(
                    f"  - `{rec.get('code')}` ({rec.get('severity')}): {rec.get('message')}"
                )
        elif r.get("issues"):
            lines.append("- issues:")
            for x in r["issues"]:
                lines.append(f"  - {x}")

        if r.get("warnings"):
            lines.append("- warnings:")
            for x in r["warnings"]:
                lines.append(f"  - {x}")

        lines.append("")
        lines.append("### Headings (preview)")
        lines.append("")
        for h in (r.get("headings") or [])[:MAX_HEADING_PREVIEW]:
            lines.append(f"- `{h}`")
        if not r.get("headings"):
            lines.append("- none")
        lines.append("")

        lines.append("### Suspicious OCR (short context only)")
        lines.append("")
        hits = r.get("suspicious_hits") or []
        if not hits:
            lines.append("- none")
        else:
            for h in hits[:20]:
                lines.append(f"- **{h.get('pattern')}**: `{h.get('context')}`")
        lines.append("")

        lines.append("### Bad tables (truncated)")
        lines.append("")
        bad = (r.get("tables") or {}).get("bad") or []
        if not bad:
            lines.append("- none")
        else:
            for b in bad[:10]:
                lines.append(
                    f"- idx={b.get('index')} reason=`{b.get('reason')}` sample=`{b.get('sample')}`"
                )
        lines.append("")

        lines.append("### Page number mapping (content_list preview)")
        lines.append("")
        for p in (r.get("page_mapping_preview") or [])[:20]:
            lines.append(f"- sample_page_idx={p.get('page_idx')} text=`{p.get('text')}`")
        if not r.get("page_mapping_preview"):
            lines.append("- none")
        lines.append("")

        lines.append("### Dose-like lines (preview, truncated)")
        lines.append("")
        doses = r.get("dose_line_preview") or []
        if not doses:
            lines.append("- none")
        else:
            for d in doses[:8]:
                lines.append(f"- `{d}`")
        lines.append("")

    lines.append("## Gate summary")
    lines.append("")
    lines.append("- Publication path requires `terminal_status=pass` for every sample.")
    lines.append("- `needs_review` and `fail` produce nonzero CLI exit code.")
    lines.append("- Summary artifacts must not embed full source markdown.")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def assert_summary_has_no_full_text(report: dict[str, Any], source_md: str) -> None:
    """Test helper: summary fields must not contain the full source body."""
    import json

    blob = json.dumps(report.get("summary") or build_report_summary(report), ensure_ascii=False)
    if len(source_md) >= 40 and source_md in blob:
        raise AssertionError("summary embeds full source markdown")


__all__ = [
    "QUALITY_PIPELINE_VERSION",
    "SUSPICIOUS_OCR_PATTERNS",
    "aggregate_gate_result",
    "assert_summary_has_no_full_text",
    "build_report_summary",
    "quality_report_for_dir",
    "write_quality_markdown",
]
