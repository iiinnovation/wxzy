"""CLI for chapter-aware PDF splits (DOC-002)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.split import (
    SplitError,
    plan_page_ranges,
    run_split_corpus,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Chapter-aware PDF split for the 7-book corpus (DOC-002)"
    )
    p.add_argument("--root", default=str(ROOT), help="repository root")
    p.add_argument(
        "--inventory",
        default=None,
        help="publication inventory JSON (default: data/.../documents.v1.json)",
    )
    p.add_argument(
        "--local-manifest",
        default=None,
        help="local-only sources manifest (optional absolute paths)",
    )
    p.add_argument(
        "--source-dir",
        default=None,
        help="directory of source PDFs (default: <root>/docs)",
    )
    p.add_argument(
        "--document-key",
        action="append",
        dest="document_keys",
        default=None,
        help="limit to document_key (repeatable)",
    )
    p.add_argument(
        "--no-detect-chapters",
        action="store_true",
        help="skip text-based chapter detection; use 20–30 page windows only",
    )
    p.add_argument(
        "--plan-only",
        action="store_true",
        help="write manifests without extracting split PDFs",
    )
    p.add_argument("--min-pages", type=int, default=20)
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--target-pages", type=int, default=25)
    p.add_argument(
        "--max-split-bytes",
        type=int,
        default=180 * 1024 * 1024,
        help="reject materialised splits larger than this (default 180MB)",
    )
    p.add_argument(
        "--print-plan",
        type=int,
        metavar="PAGE_COUNT",
        default=None,
        help="print planned ranges for a synthetic page_count and exit",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.print_plan is not None:
        ranges = plan_page_ranges(
            args.print_plan,
            min_pages=args.min_pages,
            max_pages=args.max_pages,
            target_pages=args.target_pages,
        )
        print(json.dumps(ranges, ensure_ascii=False, indent=2))
        return

    root = Path(args.root).expanduser().resolve()
    try:
        summary = run_split_corpus(
            root=root,
            inventory_path=Path(args.inventory).expanduser().resolve() if args.inventory else None,
            local_manifest_path=Path(args.local_manifest).expanduser().resolve()
            if args.local_manifest
            else None,
            source_dir=Path(args.source_dir).expanduser().resolve() if args.source_dir else None,
            document_keys=args.document_keys,
            detect_chapters=not args.no_detect_chapters,
            write_pdfs=not args.plan_only,
            min_pages=args.min_pages,
            max_pages=args.max_pages,
            target_pages=args.target_pages,
            max_split_bytes=args.max_split_bytes,
        )
    except SplitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc

    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
