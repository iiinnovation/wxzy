"""CLI for MinerU job lifecycle (P3-T04).

Stages: create -> submit -> poll -> download

Examples:
  python tools/mineru_jobs.py create --file path.pdf --split-id a --pages 10
  python tools/mineru_jobs.py submit <job_id>
  python tools/mineru_jobs.py poll <job_id>
  python tools/mineru_jobs.py download <job_id>
  python tools/mineru_jobs.py show <job_id>
  python tools/mineru_jobs.py create-from-split --manifest data/.../split-manifest.json --limit 6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.document_pipeline.env import get_token, load_env
from tools.document_pipeline.jobs import (
    DEFAULT_BUDGET_LEDGER_REL,
    HttpMinerUClient,
    JobError,
    JobFileSpec,
    create_job,
    create_job_from_split_manifest,
    download_job,
    job_path,
    load_events,
    load_manifest,
    poll_job,
    submit_job,
)
from tools.document_pipeline.paths import DEFAULT_MINERU_BASE, ROOT


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).expanduser().resolve()


def _client(args: argparse.Namespace) -> HttpMinerUClient:
    load_env(root=_root(args))
    return HttpMinerUClient(
        base_url=args.base.rstrip("/"),
        token=get_token(),
        timeout=int(getattr(args, "http_timeout", 60)),
    )


def cmd_create(args: argparse.Namespace) -> None:
    root = _root(args)
    files = list(args.file or [])
    split_ids = list(args.split_id or [])
    pages = list(args.pages or [])
    if not files:
        raise SystemExit("create requires at least one --file")
    if len(split_ids) not in {0, len(files)}:
        raise SystemExit("--split-id count must match --file count (or be omitted)")
    if len(pages) not in {0, len(files)}:
        raise SystemExit("--pages count must match --file count (or be omitted)")

    specs: list[JobFileSpec] = []
    for i, f in enumerate(files):
        path = Path(f).expanduser().resolve()
        sid = split_ids[i] if split_ids else path.stem
        page_count = int(pages[i]) if pages else int(args.default_pages)
        specs.append(
            JobFileSpec(
                split_id=sid,
                source_path=path,
                page_count=page_count,
                document_key=args.document_key,
                document_version=args.document_version,
            )
        )
    try:
        manifest = create_job(
            specs,
            root=root,
            job_id=args.job_id,
            base_url=args.base,
            model_version=args.model_version,
            language=args.language,
            enable_formula=not args.no_formula,
            enable_table=not args.no_table,
            is_ocr=bool(args.is_ocr),
            page_ranges=args.page_ranges,
        )
    except JobError as exc:
        _print({"ok": False, "error": str(exc)})
        raise SystemExit(2) from exc
    _print(
        {
            "ok": True,
            "job_id": manifest["job_id"],
            "stage": manifest["stage"],
            "file_count": manifest["file_count"],
            "page_total": manifest["page_total"],
            "job_dir": str(job_path(manifest["job_id"], root=root)),
        }
    )


def cmd_create_from_split(args: argparse.Namespace) -> None:
    root = _root(args)
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"split manifest not found: {manifest_path}")
    split_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(split_manifest, dict):
        raise SystemExit("split manifest must be a JSON object")
    try:
        job = create_job_from_split_manifest(
            split_manifest,
            root=root,
            job_id=args.job_id,
            limit=args.limit,
            base_url=args.base,
            model_version=args.model_version,
            language=args.language,
            enable_formula=not args.no_formula,
            enable_table=not args.no_table,
            is_ocr=bool(args.is_ocr),
            page_ranges=args.page_ranges,
        )
    except JobError as exc:
        _print({"ok": False, "error": str(exc)})
        raise SystemExit(2) from exc
    _print(
        {
            "ok": True,
            "job_id": job["job_id"],
            "stage": job["stage"],
            "file_count": job["file_count"],
            "page_total": job["page_total"],
            "job_dir": str(job_path(job["job_id"], root=root)),
            "source_manifest": str(manifest_path),
        }
    )


def cmd_submit(args: argparse.Namespace) -> None:
    root = _root(args)
    jdir = job_path(args.job_id, root=root)
    if not (jdir / "manifest.json").is_file():
        raise SystemExit(f"job not found: {args.job_id}")
    ledger = (
        Path(args.budget_ledger).expanduser().resolve()
        if args.budget_ledger
        else root / DEFAULT_BUDGET_LEDGER_REL
    )
    client = _client(args)
    try:
        manifest = submit_job(
            jdir,
            client,
            root=root,
            budget_ledger_path=ledger,
            reserve_budget=not args.no_budget,
        )
    except JobError as exc:
        _print({"ok": False, "job_id": args.job_id, "error": str(exc)})
        raise SystemExit(2) from exc
    _print(
        {
            "ok": True,
            "job_id": manifest["job_id"],
            "stage": manifest["stage"],
            "batch_id": manifest.get("batch_id"),
            "file_count": manifest["file_count"],
            "page_total": manifest["page_total"],
            "budget": manifest.get("budget"),
        }
    )


def cmd_poll(args: argparse.Namespace) -> None:
    root = _root(args)
    jdir = job_path(args.job_id, root=root)
    if not (jdir / "manifest.json").is_file():
        raise SystemExit(f"job not found: {args.job_id}")
    client = _client(args)
    try:
        result = poll_job(
            jdir,
            client,
            timeout_seconds=float(args.timeout),
            interval_seconds=float(args.interval),
            max_rounds=args.max_rounds,
        )
    except JobError as exc:
        _print({"ok": False, "job_id": args.job_id, "error": str(exc)})
        raise SystemExit(2) from exc
    manifest = result["manifest"]
    _print(
        {
            "ok": True,
            "job_id": manifest["job_id"],
            "stage": manifest["stage"],
            "batch_id": manifest.get("batch_id"),
            "timed_out": result.get("timed_out"),
            "last_poll_summary": manifest.get("last_poll_summary"),
        }
    )


def cmd_download(args: argparse.Namespace) -> None:
    root = _root(args)
    jdir = job_path(args.job_id, root=root)
    if not (jdir / "manifest.json").is_file():
        raise SystemExit(f"job not found: {args.job_id}")
    client = _client(args)
    try:
        manifest = download_job(
            jdir,
            client,
            root=root,
            enforce_safe_zip=not args.allow_unsafe_zip,
        )
    except JobError as exc:
        _print({"ok": False, "job_id": args.job_id, "error": str(exc)})
        raise SystemExit(2) from exc
    _print(
        {
            "ok": True,
            "job_id": manifest["job_id"],
            "stage": manifest["stage"],
            "downloaded": manifest.get("downloaded"),
            "items": [
                {
                    "data_id": i.get("data_id"),
                    "state": i.get("state"),
                    "zip_sha256": i.get("zip_sha256"),
                    "raw_relpath": i.get("raw_relpath"),
                }
                for i in manifest.get("items") or []
            ],
        }
    )


def cmd_show(args: argparse.Namespace) -> None:
    root = _root(args)
    jdir = job_path(args.job_id, root=root)
    if not (jdir / "manifest.json").is_file():
        raise SystemExit(f"job not found: {args.job_id}")
    manifest = load_manifest(jdir)
    events = load_events(jdir)
    payload: dict[str, Any] = {
        "ok": True,
        "job_id": manifest["job_id"],
        "stage": manifest["stage"],
        "batch_id": manifest.get("batch_id"),
        "file_count": manifest.get("file_count"),
        "page_total": manifest.get("page_total"),
        "timed_out": manifest.get("timed_out"),
        "downloaded": manifest.get("downloaded"),
        "budget": manifest.get("budget"),
        "items": manifest.get("items"),
        "event_count": len(events),
    }
    if args.events:
        payload["events"] = events[-args.events :]
    _print(payload)


def _add_common_create_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--job-id", default=None, help="stable job id (optional)")
    p.add_argument("--base", default=DEFAULT_MINERU_BASE)
    p.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm"])
    p.add_argument("--language", default="ch")
    p.add_argument("--is-ocr", action="store_true")
    p.add_argument("--no-formula", action="store_true")
    p.add_argument("--no-table", action="store_true")
    p.add_argument("--page-ranges", default=None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MinerU job lifecycle (create/submit/poll/download)")
    p.add_argument("--root", default=str(ROOT), help="repository root")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create", help="Create a planned job from local PDF files")
    _add_common_create_flags(pc)
    pc.add_argument("--file", action="append", default=None, help="source PDF (repeatable)")
    pc.add_argument(
        "--split-id",
        action="append",
        default=None,
        help="stable split id matching each --file (optional)",
    )
    pc.add_argument(
        "--pages",
        action="append",
        type=int,
        default=None,
        help="page count for each --file (optional)",
    )
    pc.add_argument(
        "--default-pages",
        type=int,
        default=1,
        help="page count when --pages omitted (default 1)",
    )
    pc.add_argument("--document-key", default=None)
    pc.add_argument("--document-version", default=None)
    pc.set_defaults(func=cmd_create)

    pcs = sub.add_parser("create-from-split", help="Create a job from a split-manifest.json")
    _add_common_create_flags(pcs)
    pcs.add_argument("--manifest", required=True, help="path to split-manifest.json")
    pcs.add_argument("--limit", type=int, default=None, help="only first N splits")
    pcs.set_defaults(func=cmd_create_from_split)

    ps = sub.add_parser("submit", help="Apply upload URLs, upload files, reserve budget")
    ps.add_argument("job_id")
    ps.add_argument("--base", default=DEFAULT_MINERU_BASE)
    ps.add_argument("--http-timeout", type=int, default=60)
    ps.add_argument("--budget-ledger", default=None)
    ps.add_argument(
        "--no-budget",
        action="store_true",
        help="do not reserve daily file/page budget on successful submit",
    )
    ps.set_defaults(func=cmd_submit)

    pp = sub.add_parser("poll", help="Poll batch until terminal or timeout")
    pp.add_argument("job_id")
    pp.add_argument("--base", default=DEFAULT_MINERU_BASE)
    pp.add_argument("--http-timeout", type=int, default=60)
    pp.add_argument("--timeout", type=int, default=1800, help="wall-clock seconds")
    pp.add_argument("--interval", type=float, default=8.0, help="seconds between polls")
    pp.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="optional hard cap on poll rounds (for tests/smoke)",
    )
    pp.set_defaults(func=cmd_poll)

    pd = sub.add_parser("download", help="Download done zip results into job raw/")
    pd.add_argument("job_id")
    pd.add_argument("--base", default=DEFAULT_MINERU_BASE)
    pd.add_argument("--http-timeout", type=int, default=60)
    pd.add_argument(
        "--allow-unsafe-zip",
        action="store_true",
        help="disable zip-slip member checks (not recommended)",
    )
    pd.set_defaults(func=cmd_download)

    pshow = sub.add_parser("show", help="Print job manifest summary")
    pshow.add_argument("job_id")
    pshow.add_argument(
        "--events",
        type=int,
        default=0,
        metavar="N",
        help="include last N events from events.jsonl",
    )
    pshow.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except JobError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
