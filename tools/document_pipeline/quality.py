"""Automatic quality report for MinerU result directories."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.clean import clean_markdown
from tools.document_pipeline.structure import (
    find_md_and_content_list,
    load_content_list,
    page_number,
)


def quality_report_for_dir(result_dir: Path, sample_key: str | None = None) -> dict[str, Any]:
    md_path, cl_path = find_md_and_content_list(result_dir)
    report: dict[str, Any] = {
        "sample": sample_key or result_dir.name,
        "result_dir": str(result_dir),
        "markdown_path": str(md_path) if md_path else None,
        "content_list_path": str(cl_path) if cl_path else None,
        "ok": False,
        "issues": [],
        "warnings": [],
        "metrics": {},
        "suspicious_hits": [],
        "page_mapping_preview": [],
        "headings": [],
        "tables": {"html_count": 0, "pipe_md_count": 0, "samples": []},
        "cleaning_preview": {},
    }
    if md_path is None:
        report["issues"].append("missing full.md")
        return report

    md = md_path.read_text(encoding="utf-8", errors="replace")
    items = load_content_list(cl_path)
    types = Counter(str(it.get("type") or "unknown") for it in items)
    pages = sorted({page for it in items if (page := page_number(it.get("page_idx"))) is not None})

    page_numbers = []
    headers = []
    for it in items:
        t = it.get("type")
        text = it.get("text") or it.get("content") or ""
        if isinstance(text, list):
            text = " ".join(str(x) for x in text)
        text = str(text)
        if t == "page_number":
            page_numbers.append({"page_idx": it.get("page_idx"), "text": text})
        elif t in ("header", "aside_text"):
            headers.append({"type": t, "page_idx": it.get("page_idx"), "text": text[:120]})

    suspicious_patterns = {
        "学朝": r"学朝",
        "学期笔记": r"学期\s*笔记",
        "粳镶": r"粳镶",
        "咬咀": r"咬咀",
        "黎黎": r"黎黎",
        "slash_page_in_md": r"/\s*\d{2,4}",
    }
    hits = []
    for name, pat in suspicious_patterns.items():
        for m in re.finditer(pat, md):
            start = max(0, m.start() - 30)
            end = min(len(md), m.end() + 30)
            ctx = md[start:end].replace("\n", " ")
            hits.append({"pattern": name, "context": ctx})
            if len([h for h in hits if h["pattern"] == name]) >= 5:
                break

    html_tables = re.findall(r"<table[\s\S]*?</table>", md)
    pipe_tables = re.findall(r"(?m)^\|.+\|$", md)
    headings = re.findall(r"(?m)^#{1,6}\s+.+", md)

    dose_lines = []
    for line in md.splitlines():
        if re.search(r"[钱两分升合斤枚]", line) and len(line) < 160:
            if any(k in line for k in ("组成", "用法", "钱", "两", "分", "升", "合", "斤", "枚")):
                dose_lines.append(line[:160])
            if len(dose_lines) >= 20:
                break

    clean_info = clean_markdown(md)
    report["cleaning_preview"] = {
        "rule_version": clean_info.get("rule_version"),
        "rule_ids_applied": clean_info.get("rule_ids_applied") or [],
        "corrections": clean_info["corrections"],
        "replacement_count": len(clean_info.get("replacements") or []),
        "removed_header_count": clean_info["removed_header_count"],
        "removed_page_number_count": clean_info["removed_page_number_count"],
        "removed_headers": clean_info["removed_headers"][:20],
        "char_delta": clean_info["original_chars"] - clean_info["cleaned_chars"],
    }

    metrics = {
        "markdown_chars": len(md),
        "markdown_lines": md.count("\n") + 1,
        "content_list_items": len(items),
        "types_count": dict(types),
        "pages_seen": pages,
        "page_count_est": len(pages),
        "heading_count": len(headings),
        "html_table_count": len(html_tables),
        "pipe_table_count": len(pipe_tables),
        "page_number_items": len(page_numbers),
        "header_aside_items": len(headers),
        "suspicious_hit_count": len(hits),
    }
    report["metrics"] = metrics
    report["suspicious_hits"] = hits[:50]
    report["headings"] = headings[:40]
    report["tables"] = {
        "html_count": len(html_tables),
        "pipe_md_count": len(pipe_tables),
        "samples": [t[:400].replace("\n", " ") for t in html_tables[:3]],
    }
    report["page_mapping_preview"] = page_numbers
    report["header_noise_preview"] = headers[:30]
    report["dose_line_preview"] = dose_lines

    if not pages:
        report["issues"].append("content_list has no page_idx")
    elif pages != list(range(min(pages), max(pages) + 1)):
        report["warnings"].append(f"page_idx not contiguous: {pages}")
    if len(md) < 500:
        report["issues"].append("markdown too short")
    if len(hits) > 0:
        report["warnings"].append(
            f"found {len(hits)} suspicious OCR patterns; review required before cards"
        )
    if metrics["html_table_count"] == 0 and metrics["pipe_table_count"] == 0:
        report["warnings"].append("no tables detected; may be fine for prose-only pages")
    if any("学朝" in h or "学期" in h for h in headings):
        report["warnings"].append("header watermark leaked into markdown headings")

    report["ok"] = len(report["issues"]) == 0
    report["recommendation"] = (
        "PASS_WITH_CLEANING"
        if report["ok"] and len(hits) <= 8
        else "PASS"
        if report["ok"] and len(hits) == 0
        else "NEEDS_HUMAN_REVIEW"
    )
    return report


def write_quality_markdown(reports: list[dict[str, Any]], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# MinerU 自动质检报告")
    lines.append("")
    lines.append(f"- generated_at: `{datetime.now(UTC).isoformat()}`")
    lines.append(f"- samples: {len(reports)}")
    lines.append("")
    for r in reports:
        m = r.get("metrics") or {}
        lines.append(f"## {r.get('sample')}")
        lines.append("")
        lines.append(f"- ok: `{r.get('ok')}`")
        lines.append(f"- recommendation: `{r.get('recommendation')}`")
        lines.append(f"- markdown_chars: `{m.get('markdown_chars')}`")
        lines.append(f"- content_list_items: `{m.get('content_list_items')}`")
        lines.append(f"- pages_seen: `{m.get('pages_seen')}`")
        lines.append(f"- types: `{m.get('types_count')}`")
        lines.append(f"- html_tables: `{m.get('html_table_count')}`")
        lines.append(f"- headings: `{m.get('heading_count')}`")
        lines.append(f"- suspicious_hits: `{m.get('suspicious_hit_count')}`")
        cp = r.get("cleaning_preview") or {}
        lines.append(f"- cleaning corrections: `{cp.get('corrections')}`")
        lines.append(f"- removed header noise: `{cp.get('removed_header_count')}`")
        if r.get("issues"):
            lines.append("- issues:")
            for x in r["issues"]:
                lines.append(f"  - {x}")
        if r.get("warnings"):
            lines.append("- warnings:")
            for x in r["warnings"]:
                lines.append(f"  - {x}")
        lines.append("")
        lines.append("### Headings")
        lines.append("")
        for h in (r.get("headings") or [])[:20]:
            lines.append(f"- `{h}`")
        lines.append("")
        lines.append("### Suspicious OCR contexts")
        lines.append("")
        hits = r.get("suspicious_hits") or []
        if not hits:
            lines.append("- none")
        else:
            for h in hits[:20]:
                lines.append(f"- **{h['pattern']}**: {h['context']}")
        lines.append("")
        lines.append("### Page number mapping (content_list)")
        lines.append("")
        for p in (r.get("page_mapping_preview") or [])[:20]:
            lines.append(f"- sample_page_idx={p.get('page_idx')} text=`{p.get('text')}`")
        lines.append("")
        lines.append("### Dose-like lines (preview)")
        lines.append("")
        doses = r.get("dose_line_preview") or []
        if not doses:
            lines.append("- none")
        else:
            for d in doses[:15]:
                lines.append(f"- {d}")
        lines.append("")
        lines.append("### Table sample 0")
        lines.append("")
        samples = (r.get("tables") or {}).get("samples") or []
        if samples:
            lines.append("```html")
            lines.append(samples[0][:800])
            lines.append("```")
        else:
            lines.append("- none")
        lines.append("")
    lines.append("## Go / No-Go 建议（自动）")
    lines.append("")
    lines.append("- 链路可用：上传→解析→下载已验证。")
    lines.append(
        "- 卡片生成前必须：1) 去掉页眉水印；2) 人工确认剂量/方歌 OCR；3) 多教材版本分类不可混写。"
    )
    lines.append("- 推荐默认清洗后再喂给 Qwen，不可直接把 raw full.md 当事实源。")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
