"""CLI commands for MinerU validation (compat surface)."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from urllib.request import Request, urlopen

from tools.document_pipeline.clean import write_cleaned_markdown
from tools.document_pipeline.env import get_token, load_env
from tools.document_pipeline.http_client import http_json, put_file
from tools.document_pipeline.page_mapping import enrich_page_map_from_content_list_path
from tools.document_pipeline.pages import parse_pages
from tools.document_pipeline.paths import (
    DEFAULT_MINERU_BASE,
    DEFAULT_RESULTS,
    DEFAULT_RUNS,
    DEFAULT_SAMPLES,
    ROOT,
)
from tools.document_pipeline.quality import quality_report_for_dir, write_quality_markdown
from tools.document_pipeline.raw import materialize_raw_from_zip, summarize_result_dir, unpack_zip
from tools.document_pipeline.split import extract_pages
from tools.document_pipeline.structure import find_md_and_content_list

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


class SampleSpec(TypedDict):
    key: str
    src: Path
    pages: list[int]
    out: Path


def cmd_quality_report(args: argparse.Namespace) -> None:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path not found: {target}")

    sample_dirs: list[Path] = []
    if (target / "unzipped").is_dir() or list(target.rglob("full.md")):
        if (target / "unzipped").is_dir() or (target / "full.md").is_file():
            sample_dirs = [target]
        else:
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
    out_json = (
        Path(args.out_json).expanduser().resolve()
        if args.out_json
        else (target / "auto_quality_report.json")
    )
    out_md = (
        Path(args.out_md).expanduser().resolve()
        if args.out_md
        else (target / "AUTO_QUALITY_REPORT.md")
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    write_quality_markdown(reports, out_md)
    print(
        json.dumps(
            {
                "samples": len(reports),
                "out_json": str(out_json),
                "out_md": str(out_md),
                "recommendations": {r["sample"]: r.get("recommendation") for r in reports},
                "ok": {r["sample"]: r.get("ok") for r in reports},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_clean_md(args: argparse.Namespace) -> None:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"path not found: {target}")

    md_path, cl_path = find_md_and_content_list(target)
    if md_path is None and target.is_file() and target.suffix == ".md":
        md_path = target
    if md_path is None:
        raise SystemExit(f"full.md not found under {target}")

    out = Path(args.out).expanduser().resolve() if args.out else None
    page_map = None
    if cl_path is not None and cl_path.is_file():
        page_map = enrich_page_map_from_content_list_path(
            cl_path,
            source_pdf_page_start=int(args.source_pdf_page_start)
            if getattr(args, "source_pdf_page_start", None)
            else None,
            expected_page_count=int(args.expected_pages)
            if getattr(args, "expected_pages", None)
            else None,
        )
    try:
        result = write_cleaned_markdown(md_path, out=out, page_map=page_map)
    except Exception as exc:  # noqa: BLE001 - CLI surface
        # Fallback for non-raw paths still uses pure clean_markdown if write guard fails unexpectedly
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def cmd_extract(args: argparse.Namespace) -> None:
    pages = parse_pages(args.pages)
    meta = extract_pages(
        Path(args.src).expanduser().resolve(), pages, Path(args.out).expanduser().resolve()
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


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
    for f, url in zip(files, urls, strict=True):
        print(f"uploading {f.name} ({f.stat().st_size} bytes)...")
        code = put_file(url, f)
        print(f"  upload HTTP {code}")

    run_dir = DEFAULT_RUNS / batch_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
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
                progress.append(f"{name}:{st} {ep.get('extracted_pages')}/{ep.get('total_pages')}")
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
                "polled_at": datetime.now(UTC).isoformat(),
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
        try:
            raw_meta = materialize_raw_from_zip(zip_path, item_dir, require_markdown=False)
            names = list(raw_meta.get("members_sample") or [])
        except Exception:
            names = unpack_zip(zip_path, item_dir / "unzipped", enforce_safe_members=True)
            raw_meta = None
        summary = summarize_result_dir(item_dir / "unzipped")
        if raw_meta is not None:
            summary["zip_sha256"] = raw_meta.get("zip_sha256")
            summary["output_hashes"] = raw_meta.get("output_hashes")
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
        "downloaded_at": datetime.now(UTC).isoformat(),
        "items": summaries,
    }
    report_path = batch_out / "download_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={report_path}")


def cmd_run_samples(args: argparse.Namespace) -> None:
    """Extract representative samples and run full MinerU flow."""
    load_env()
    token = get_token()
    _ = token

    samples_spec: list[SampleSpec] = [
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

    extracted: list[dict[str, Any]] = []
    for item in samples_spec:
        if not item["src"].is_file():
            raise SystemExit(f"missing source: {item['src']}")
        if fitz is None:
            raise SystemExit("PyMuPDF (fitz) is required: pip install pymupdf")
        doc = fitz.open(item["src"])
        total = int(doc.page_count)
        doc.close()
        pages = [p for p in item["pages"] if 1 <= p <= total]
        if len(pages) < 8:
            pages = list(range(3, min(total, 13)))
        meta = extract_pages(item["src"], pages, item["out"])
        meta["key"] = item["key"]
        extracted.append(meta)
        print(f"extracted {item['key']}: pages={pages} size={meta['output_size_bytes']}")

    files = [item["out"] for item in samples_spec]
    print("submitting samples...")
    token = get_token()
    base = args.base.rstrip("/")
    file_specs = []
    for f, meta in zip(files, extracted, strict=True):
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
    for f, url in zip(files, urls, strict=True):
        print(f"uploading {f.name} ({f.stat().st_size} bytes)...")
        code = put_file(url, f)
        print(f"  upload HTTP {code}")

    run_dir = DEFAULT_RUNS / batch_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
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
    dl_ns = argparse.Namespace(
        batch_id=batch_id, base=args.base, out=str(DEFAULT_RESULTS / batch_id)
    )
    cmd_download(dl_ns)
    print(f"DONE batch_id={batch_id}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MinerU local validation tools")
    p.add_argument("--base", default=DEFAULT_MINERU_BASE)
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

    pq = sub.add_parser(
        "quality-report", help="Scan MinerU result dir(s) and write auto quality report"
    )
    pq.add_argument("path", help="batch result dir or single sample dir")
    pq.add_argument("--out-json")
    pq.add_argument("--out-md")
    pq.set_defaults(func=cmd_quality_report)

    pc = sub.add_parser("clean-md", help="Apply deterministic OCR/header cleaning to full.md")
    pc.add_argument("path", help="sample result dir or full.md path")
    pc.add_argument("--out", help="output cleaned markdown path")
    pc.add_argument(
        "--source-pdf-page-start",
        type=int,
        default=None,
        help="1-based source PDF page for split page 0 (page map)",
    )
    pc.add_argument(
        "--expected-pages",
        type=int,
        default=None,
        help="expected split page count for complete page map",
    )
    pc.set_defaults(func=cmd_clean_md)

    return p


def main() -> None:
    load_env()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
