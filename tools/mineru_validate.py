#!/usr/bin/env python3
"""MinerU local validation helper.

Reads MINERU_API_TOKEN from environment or .env.local.
Never prints the token value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://mineru.net"
DEFAULT_SAMPLES = ROOT / "data" / "mineru" / "samples"
DEFAULT_RESULTS = ROOT / "data" / "mineru" / "results"
DEFAULT_RUNS = ROOT / "data" / "mineru" / "runs"


def load_env() -> None:
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def get_token() -> str:
    token = os.environ.get("MINERU_API_TOKEN") or os.environ.get("MINERU_TOKEN")
    if not token:
        raise SystemExit(
            "MINERU_API_TOKEN is not set. Put it in .env.local or export it."
        )
    return token


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except HTTPError as e:
        raw = e.read()
        status = e.code
    except URLError as e:
        raise SystemExit(f"network error calling {url}: {e}") from e
    text = raw.decode("utf-8", errors="replace") if raw else ""
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = {"raw": text[:1000]}
    return status, payload


def put_file(upload_url: str, file_path: Path, timeout: int = 300) -> int:
    """Upload with no Content-Type header.

    MinerU docs require: requests.put(url, data=f)
    Adding Content-Type breaks Aliyun OSS pre-signed URL signatures.
    urllib also auto-injects application/x-www-form-urlencoded, so use requests.
    """
    try:
        import requests
    except ImportError as e:  # pragma: no cover
        raise SystemExit("requests is required for OSS upload: pip install requests") from e
    with open(file_path, "rb") as f:
        resp = requests.put(upload_url, data=f, timeout=timeout)
    if resp.status_code not in (200, 201):
        raise SystemExit(
            f"upload failed HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return resp.status_code


def extract_pages(src: Path, pages: list[int], out: Path) -> dict[str, Any]:
    if fitz is None:
        raise SystemExit("PyMuPDF (fitz) is required: pip install pymupdf")
    if not src.is_file():
        raise SystemExit(f"source PDF not found: {src}")
    doc = fitz.open(src)
    total = doc.page_count
    # pages are 1-based inclusive from user
    selected = []
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
        "source": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
        "source_pages_total": total,
        "selected_pages_1based": pages,
        "output": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
        "output_pages": new_doc.page_count,
        "output_size_bytes": out.stat().st_size,
    }
    new_doc.close()
    doc.close()
    return meta


def unpack_zip(zip_path: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
        names = zf.namelist()
    return names


def summarize_result_dir(result_dir: Path) -> dict[str, Any]:
    files = sorted(p.relative_to(result_dir).as_posix() for p in result_dir.rglob("*") if p.is_file())
    md_files = [p for p in result_dir.rglob("*.md")]
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
        items = raw if isinstance(raw, list) else raw.get("pdf_info") or raw.get("content_list") or []
        if isinstance(items, list):
            summary["content_list_items"] = len(items)
            pages = set()
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



OCR_CORRECTIONS = [
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

HEADER_NOISE_PATTERNS = [
    r"^##?\s*中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
    r"^中医考研\s*(学朝|学期|学霸)\s*笔记\s*$",
]

PAGE_NUMBER_PATTERNS = [
    r"^/\s*\d{2,4}\s*$",
    r"^\d{2,4}\s*$",
]


def find_md_and_content_list(result_dir: Path) -> tuple[Path | None, Path | None]:
    md = None
    cl = None
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


def clean_markdown(md: str) -> dict[str, Any]:
    import re

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
                    # only strip bare page-number-like lines, not content
                    removed_page_numbers.append(stripped)
                    is_noise = True
                    break
        if not is_noise:
            kept_lines.append(line)

    # collapse excessive blank lines
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


def quality_report_for_dir(result_dir: Path, sample_key: str | None = None) -> dict[str, Any]:
    import re
    from collections import Counter

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
    pages = sorted({it.get("page_idx") for it in items if it.get("page_idx") is not None})

    # page numbers / headers from content_list
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

    # dose-like lines for manual review anchors
    dose_lines = []
    for line in md.splitlines():
        if re.search(r"[钱两分升合斤枚]", line) and len(line) < 160:
            if any(k in line for k in ("组成", "用法", "钱", "两", "分", "升", "合", "斤", "枚")):
                dose_lines.append(line[:160])
            if len(dose_lines) >= 20:
                break

    clean_info = clean_markdown(md)
    report["cleaning_preview"] = {
        "corrections": clean_info["corrections"],
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

    # hard checks
    if not pages:
        report["issues"].append("content_list has no page_idx")
    elif pages != list(range(min(pages), max(pages) + 1)):
        report["warnings"].append(f"page_idx not contiguous: {pages}")
    if len(md) < 500:
        report["issues"].append("markdown too short")
    if metrics["suspicious_hit_count"] > 0:
        report["warnings"].append(
            f"found {metrics['suspicious_hit_count']} suspicious OCR patterns; review required before cards"
        )
    if metrics["html_table_count"] == 0 and metrics["pipe_table_count"] == 0:
        report["warnings"].append("no tables detected; may be fine for prose-only pages")
    if any("学朝" in h or "学期" in h for h in headings):
        report["warnings"].append("header watermark leaked into markdown headings")

    report["ok"] = len(report["issues"]) == 0
    report["recommendation"] = (
        "PASS_WITH_CLEANING" if report["ok"] and metrics["suspicious_hit_count"] <= 8 else
        "PASS" if report["ok"] and metrics["suspicious_hit_count"] == 0 else
        "NEEDS_HUMAN_REVIEW"
    )
    return report


def write_quality_markdown(reports: list[dict[str, Any]], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# MinerU 自动质检报告")
    lines.append("")
    lines.append(f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`")
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
    lines.append("- 卡片生成前必须：1) 去掉页眉水印；2) 人工确认剂量/方歌 OCR；3) 多教材版本分类不可混写。")
    lines.append("- 推荐默认清洗后再喂给 Qwen，不可直接把 raw full.md 当事实源。")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def cmd_quality_report(args: argparse.Namespace) -> None:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path not found: {target}")

    sample_dirs: list[Path] = []
    if (target / "unzipped").is_dir() or list(target.rglob("full.md")):
        # single sample dir or already result root with full.md deeper
        if (target / "unzipped").is_dir() or (target / "full.md").is_file():
            sample_dirs = [target]
        else:
            # batch root: each child sample
            for child in sorted(target.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    md, _ = find_md_and_content_list(child)
                    if md is not None:
                        sample_dirs.append(child)
    else:
        raise SystemExit(f"no mineru result markdown under {target}")

    if not sample_dirs:
        raise SystemExit(f"no sample result dirs found under {target}")

    reports = [quality_report_for_dir(d, sample_key=d.name) for d in sample_dirs]
    out_json = Path(args.out_json).expanduser().resolve() if args.out_json else (target / "auto_quality_report.json")
    out_md = Path(args.out_md).expanduser().resolve() if args.out_md else (target / "AUTO_QUALITY_REPORT.md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    write_quality_markdown(reports, out_md)
    print(json.dumps({
        "samples": len(reports),
        "out_json": str(out_json),
        "out_md": str(out_md),
        "recommendations": {r["sample"]: r.get("recommendation") for r in reports},
        "ok": {r["sample"]: r.get("ok") for r in reports},
    }, ensure_ascii=False, indent=2))


def cmd_clean_md(args: argparse.Namespace) -> None:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path not found: {target}")

    md_path, _ = find_md_and_content_list(target)
    if md_path is None and target.is_file() and target.suffix == ".md":
        md_path = target
    if md_path is None:
        raise SystemExit(f"full.md not found under {target}")

    md = md_path.read_text(encoding="utf-8", errors="replace")
    info = clean_markdown(md)
    if args.out:
        out = Path(args.out).expanduser().resolve()
    else:
        out = md_path.with_name("full.cleaned.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(info["cleaned_md"], encoding="utf-8")
    meta = {k: v for k, v in info.items() if k != "cleaned_md"}
    meta_path = out.with_suffix(out.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "source": str(md_path),
        "out": str(out),
        "meta": str(meta_path),
        **meta,
    }, ensure_ascii=False, indent=2))


def cmd_extract(args: argparse.Namespace) -> None:
    pages = parse_pages(args.pages)
    meta = extract_pages(Path(args.src).expanduser().resolve(), pages, Path(args.out).expanduser().resolve())
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def parse_pages(spec: str) -> list[int]:
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
    # unique preserve order
    seen = set()
    out = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            out.append(p)
    if not out:
        raise SystemExit("no pages selected")
    return out


def cmd_submit(args: argparse.Namespace) -> None:
    load_env()
    token = get_token()
    base = args.base.rstrip("/")
    files = [Path(p).expanduser().resolve() for p in args.files]
    for f in files:
        if not f.is_file():
            raise SystemExit(f"file not found: {f}")
        if f.stat().st_size > 200 * 1024 * 1024:
            raise SystemExit(f"file exceeds 200MB: {f}")

    file_specs = []
    for f in files:
        data_id = args.data_id or f.stem[:80]
        # sanitize data_id
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in data_id)[:128]
        item: dict[str, Any] = {"name": f.name, "data_id": safe}
        if args.is_ocr:
            item["is_ocr"] = True
        if args.page_ranges:
            item["page_ranges"] = args.page_ranges
        file_specs.append(item)

    body: dict[str, Any] = {
        "files": file_specs,
        "model_version": args.model_version,
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table,
        "language": args.language,
    }

    status, payload = http_json("POST", f"{base}/api/v4/file-urls/batch", token=token, body=body)
    if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
        raise SystemExit(f"apply upload urls failed: status={status} body={payload}")

    data = payload["data"]
    batch_id = data["batch_id"]
    urls = data["file_urls"]
    if len(urls) != len(files):
        raise SystemExit(f"url count mismatch: files={len(files)} urls={len(urls)}")

    print(f"batch_id={batch_id}")
    for f, url in zip(files, urls):
        print(f"uploading {f.name} ({f.stat().st_size} bytes)...")
        code = put_file(url, f)
        print(f"  upload HTTP {code}")

    run_dir = DEFAULT_RUNS / batch_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "base": base,
        "model_version": args.model_version,
        "language": args.language,
        "enable_formula": not args.no_formula,
        "enable_table": not args.no_table,
        "is_ocr": bool(args.is_ocr),
        "files": [
            {
                "path": str(f),
                "name": f.name,
                "size": f.stat().st_size,
                "data_id": file_specs[i]["data_id"],
            }
            for i, f in enumerate(files)
        ],
        "apply_response": payload,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest={run_dir / 'manifest.json'}")
    print(batch_id)


def cmd_poll(args: argparse.Namespace) -> None:
    load_env()
    token = get_token()
    base = args.base.rstrip("/")
    batch_id = args.batch_id
    url = f"{base}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.time() + args.timeout
    last_states: list[str] = []

    while True:
        status, payload = http_json("GET", url, token=token)
        if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            raise SystemExit(f"poll failed: status={status} body={payload}")
        results = payload.get("data", {}).get("extract_result") or []
        states = [r.get("state", "?") for r in results]
        progress = []
        for r in results:
            name = r.get("file_name") or r.get("data_id") or "?"
            st = r.get("state")
            if st == "running" and r.get("extract_progress"):
                ep = r["extract_progress"]
                progress.append(
                    f"{name}:{st} {ep.get('extracted_pages')}/{ep.get('total_pages')}"
                )
            else:
                progress.append(f"{name}:{st}")
        msg = " | ".join(progress) if progress else f"states={states}"
        if states != last_states:
            print(f"[{int(time.time())}] {msg}")
            last_states = states
        else:
            print(f"[{int(time.time())}] {msg}")

        terminal = {"done", "failed"}
        if results and all(r.get("state") in terminal for r in results):
            out = {
                "polled_at": datetime.now(timezone.utc).isoformat(),
                "batch_id": batch_id,
                "payload": payload,
            }
            run_dir = DEFAULT_RUNS / batch_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "poll.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if any(r.get("state") == "failed" for r in results):
                raise SystemExit("one or more tasks failed")
            return

        if time.time() >= deadline:
            raise SystemExit(f"timeout after {args.timeout}s; last={msg}")
        time.sleep(args.interval)


def cmd_download(args: argparse.Namespace) -> None:
    load_env()
    token = get_token()
    base = args.base.rstrip("/")
    batch_id = args.batch_id
    status, payload = http_json(
        "GET", f"{base}/api/v4/extract-results/batch/{batch_id}", token=token
    )
    if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
        raise SystemExit(f"fetch batch failed: status={status} body={payload}")
    results = payload.get("data", {}).get("extract_result") or []
    if not results:
        raise SystemExit("no extract_result in batch")

    batch_out = Path(args.out or (DEFAULT_RESULTS / batch_id)).expanduser().resolve()
    batch_out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for r in results:
        name = r.get("file_name") or r.get("data_id") or "item"
        state = r.get("state")
        if state != "done":
            summaries.append({"file_name": name, "state": state, "err_msg": r.get("err_msg")})
            continue
        zip_url = r.get("full_zip_url")
        if not zip_url:
            summaries.append({"file_name": name, "state": state, "error": "missing full_zip_url"})
            continue
        safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
        item_dir = batch_out / Path(safe_name).stem
        item_dir.mkdir(parents=True, exist_ok=True)
        zip_path = item_dir / "result.zip"
        print(f"downloading {name} -> {zip_path}")
        req = Request(zip_url, method="GET")
        with urlopen(req, timeout=180) as resp:
            zip_path.write_bytes(resp.read())
        names = unpack_zip(zip_path, item_dir / "unzipped")
        summary = summarize_result_dir(item_dir / "unzipped")
        summary.update(
            {
                "file_name": name,
                "state": state,
                "data_id": r.get("data_id"),
                "zip_path": str(zip_path),
                "zip_entries": names[:100],
            }
        )
        (item_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summaries.append(summary)
        print(
            f"  files={summary['file_count']} md_chars={summary['markdown_chars']} "
            f"content_items={summary['content_list_items']} types={summary.get('types_count')}"
        )

    report = {
        "batch_id": batch_id,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "items": summaries,
    }
    report_path = batch_out / "download_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={report_path}")


def cmd_run_samples(args: argparse.Namespace) -> None:
    """Extract representative samples and run full MinerU flow."""
    load_env()
    token = get_token()
    _ = token  # ensure present early

    samples_spec = [
        {
            "key": "neike_sample",
            "src": ROOT / "docs" / "学霸笔记—中医内科学(1).pdf",
            "pages": [5, 6, 20, 21, 40, 41, 60, 80, 100, 120],
            "out": DEFAULT_SAMPLES / "neike_10p.pdf",
        },
        {
            "key": "fangji_sample",
            "src": ROOT / "docs" / "学霸笔记—方剂学(1).pdf",
            "pages": [5, 6, 20, 21, 40, 41, 60, 80, 100, 120],
            "out": DEFAULT_SAMPLES / "fangji_10p.pdf",
        },
    ]

    extracted = []
    for item in samples_spec:
        if not item["src"].is_file():
            raise SystemExit(f"missing source: {item['src']}")
        # clamp pages to available
        doc = fitz.open(item["src"])
        total = doc.page_count
        doc.close()
        pages = [p for p in item["pages"] if 1 <= p <= total]
        if len(pages) < 8:
            # fallback denser early pages
            pages = list(range(3, min(total, 13)))
        meta = extract_pages(item["src"], pages, item["out"])
        meta["key"] = item["key"]
        extracted.append(meta)
        print(f"extracted {item['key']}: pages={pages} size={meta['output_size_bytes']}")

    # submit
    files = [Path(m["output"]).resolve() if Path(m["output"]).is_absolute() else (ROOT / m["output"]).resolve() for m in extracted]
    # rebuild absolute from out paths we just wrote
    files = [item["out"] for item in samples_spec]
    submit_ns = argparse.Namespace(
        files=[str(f) for f in files],
        base=args.base,
        model_version=args.model_version,
        language=args.language,
        is_ocr=args.is_ocr,
        no_formula=False,
        no_table=False,
        page_ranges=None,
        data_id=None,
    )
    # capture batch_id by reusing submit internals
    print("submitting samples...")
    # Call submit and read last printed batch id via run dir listing is brittle;
    # re-implement submit inline for return value.
    token = get_token()
    base = args.base.rstrip("/")
    file_specs = []
    for f, meta in zip(files, extracted):
        data_id = meta["key"]
        file_specs.append(
            {
                "name": f.name,
                "data_id": data_id,
                **({"is_ocr": True} if args.is_ocr else {}),
            }
        )
    body = {
        "files": file_specs,
        "model_version": args.model_version,
        "enable_formula": True,
        "enable_table": True,
        "language": args.language,
    }
    status, payload = http_json("POST", f"{base}/api/v4/file-urls/batch", token=token, body=body)
    if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
        raise SystemExit(f"apply upload urls failed: status={status} body={payload}")
    batch_id = payload["data"]["batch_id"]
    urls = payload["data"]["file_urls"]
    print(f"batch_id={batch_id}")
    for f, url in zip(files, urls):
        print(f"uploading {f.name} ({f.stat().st_size} bytes)...")
        code = put_file(url, f)
        print(f"  upload HTTP {code}")

    run_dir = DEFAULT_RUNS / batch_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "mode": "run-samples",
        "extracted": extracted,
        "model_version": args.model_version,
        "language": args.language,
        "is_ocr": bool(args.is_ocr),
        "apply_response": payload,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    poll_ns = argparse.Namespace(
        batch_id=batch_id, base=args.base, timeout=args.timeout, interval=args.interval
    )
    cmd_poll(poll_ns)
    dl_ns = argparse.Namespace(batch_id=batch_id, base=args.base, out=str(DEFAULT_RESULTS / batch_id))
    cmd_download(dl_ns)
    print(f"DONE batch_id={batch_id}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MinerU local validation tools")
    p.add_argument("--base", default=DEFAULT_BASE)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract-pages", help="Extract page ranges into a smaller PDF")
    pe.add_argument("--src", required=True)
    pe.add_argument("--pages", required=True, help="e.g. 5-6,20,40-41")
    pe.add_argument("--out", required=True)
    pe.set_defaults(func=cmd_extract)

    ps = sub.add_parser("submit", help="Apply upload URLs and upload local files")
    ps.add_argument("files", nargs="+")
    ps.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm"])
    ps.add_argument("--language", default="ch")
    ps.add_argument("--is-ocr", action="store_true")
    ps.add_argument("--no-formula", action="store_true")
    ps.add_argument("--no-table", action="store_true")
    ps.add_argument("--page-ranges")
    ps.add_argument("--data-id")
    ps.set_defaults(func=cmd_submit)

    pp = sub.add_parser("poll", help="Poll batch status until done/failed")
    pp.add_argument("batch_id")
    pp.add_argument("--timeout", type=int, default=1800)
    pp.add_argument("--interval", type=int, default=8)
    pp.set_defaults(func=cmd_poll)

    pd = sub.add_parser("download", help="Download and unpack full_zip_url results")
    pd.add_argument("batch_id")
    pd.add_argument("--out")
    pd.set_defaults(func=cmd_download)

    pr = sub.add_parser("run-samples", help="Extract two 10-page samples and process end-to-end")
    pr.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm"])
    pr.add_argument("--language", default="ch")
    pr.add_argument("--is-ocr", action="store_true")
    pr.add_argument("--timeout", type=int, default=1800)
    pr.add_argument("--interval", type=int, default=8)
    pr.set_defaults(func=cmd_run_samples)


    pq = sub.add_parser("quality-report", help="Scan MinerU result dir(s) and write auto quality report")
    pq.add_argument("path", help="batch result dir or single sample dir")
    pq.add_argument("--out-json")
    pq.add_argument("--out-md")
    pq.set_defaults(func=cmd_quality_report)

    pc = sub.add_parser("clean-md", help="Apply deterministic OCR/header cleaning to full.md")
    pc.add_argument("path", help="sample result dir or full.md path")
    pc.add_argument("--out", help="output cleaned markdown path")
    pc.set_defaults(func=cmd_clean_md)

    return p


def main() -> None:
    load_env()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
