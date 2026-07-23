"""CLI for document inventory scans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.document_pipeline.inventory import (
    InventoryError,
    default_inventory_path,
    default_local_manifest_path,
    run_inventory,
)
from tools.document_pipeline.paths import ROOT


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scan docs/*.pdf into document inventory (DOC-001)")
    p.add_argument(
        "--root",
        default=str(ROOT),
        help="repository root (default: auto-detected)",
    )
    p.add_argument(
        "--source-dir",
        default=None,
        help="directory of source PDFs (default: <root>/docs)",
    )
    p.add_argument(
        "--out",
        default=None,
        help="publication-safe inventory JSON path",
    )
    p.add_argument(
        "--local-manifest",
        default=None,
        help="local-only absolute-path manifest path",
    )
    p.add_argument(
        "--no-local-manifest",
        action="store_true",
        help="do not write the local absolute-path manifest",
    )
    p.add_argument(
        "--copyright-scope",
        default="personal-use",
        help="copyright note recorded on each document version",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="do not require the full 7-book expected key set",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    out = Path(args.out).expanduser().resolve() if args.out else default_inventory_path(root=root)
    local = (
        None
        if args.no_local_manifest
        else (
            Path(args.local_manifest).expanduser().resolve()
            if args.local_manifest
            else default_local_manifest_path(root=root)
        )
    )
    try:
        summary = run_inventory(
            root=root,
            source_dir=source_dir,
            out_path=out,
            local_manifest_path=local,
            copyright_scope=args.copyright_scope,
            write_local_manifest=not args.no_local_manifest,
            require_expected_keys=not args.allow_partial,
        )
    except InventoryError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
