"""CLI commands for offline/API candidate card generation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from tools.document_pipeline.env import load_env
from tools.document_pipeline.generation import (
    DEFAULT_BATCH,
    PROMPT_VERSION,
    ROOT,
    call_qwen_api,
    extract_formula_cards,
    extract_neike_pulmonary_tb_cards,
    extract_versioned_zhongfeng_cards,
    now_iso,
    write_review_md,
)


def cmd_offline(args: argparse.Namespace) -> None:
    batch_id = args.batch_id
    fang_path = Path(args.fangji).expanduser().resolve()
    nei_path = Path(args.neike).expanduser().resolve()
    fang_md = fang_path.read_text(encoding="utf-8")
    nei_md = nei_path.read_text(encoding="utf-8")

    targets = set(args.formulas.split(",")) if args.formulas else {"桂枝汤", "白虎汤"}
    cards: list[dict[str, Any]] = []
    fang_cards = extract_formula_cards(
        fang_md,
        book="方剂学",
        source_file=str(fang_path.relative_to(ROOT))
        if fang_path.is_relative_to(ROOT)
        else str(fang_path),
        batch_id=batch_id,
        targets=targets,
    )
    chapter_map = {
        "桂枝汤": "解表剂",
        "小青龙汤": "解表剂",
        "白虎汤": "清热剂",
        "竹叶石膏汤": "清热剂",
        "当归四逆汤": "温里剂",
        "阳和汤": "温里剂",
    }
    for c in fang_cards:
        sec = c.get("section")
        if sec in chapter_map:
            c["chapter"] = chapter_map[sec]
    cards.extend(fang_cards)
    cards.extend(
        extract_neike_pulmonary_tb_cards(
            nei_md,
            source_file=str(nei_path.relative_to(ROOT))
            if nei_path.is_relative_to(ROOT)
            else str(nei_path),
            batch_id=batch_id,
        )
    )
    if args.include_zhongfeng:
        cards.extend(
            extract_versioned_zhongfeng_cards(
                nei_md,
                source_file=str(nei_path.relative_to(ROOT))
                if nei_path.is_relative_to(ROOT)
                else str(nei_path),
                batch_id=batch_id,
            )
        )

    out_json = Path(args.out).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "mode": "offline",
        "batch_id": batch_id,
        "prompt_version": PROMPT_VERSION,
        "generated_at": now_iso(),
        "count": len(cards),
        "cards": cards,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = (
        Path(args.review_md).expanduser().resolve()
        if args.review_md
        else out_json.with_suffix(".REVIEW.md")
    )
    write_review_md(cards, out_md)
    print(
        json.dumps(
            {
                "count": len(cards),
                "out": str(out_json),
                "review_md": str(out_md),
                "by_status": {
                    s: sum(1 for c in cards if c["status"] == s)
                    for s in sorted({c["status"] for c in cards})
                },
                "sections": sorted({c.get("section") for c in cards if c.get("section")}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_api(args: argparse.Namespace) -> None:
    load_env()
    path = Path(args.input).expanduser().resolve()
    md = path.read_text(encoding="utf-8")
    chunk = md[: args.max_chars]
    cards = call_qwen_api(chunk, book=args.book, model=args.model)
    for c in cards:
        c.setdefault("status", "candidate")
        c.setdefault(
            "trace",
            {
                "source_file": str(path),
                "batch_id": args.batch_id,
                "generator": "qwen-api",
                "model": args.model,
                "prompt_version": PROMPT_VERSION,
                "created_at": now_iso(),
            },
        )
    out_json = Path(args.out).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "mode": "api",
        "batch_id": args.batch_id,
        "prompt_version": PROMPT_VERSION,
        "model": args.model,
        "generated_at": now_iso(),
        "count": len(cards),
        "cards": cards,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = (
        Path(args.review_md).expanduser().resolve()
        if args.review_md
        else out_json.with_suffix(".REVIEW.md")
    )
    write_review_md(cards, out_md)
    print(
        json.dumps(
            {"count": len(cards), "out": str(out_json), "review_md": str(out_md)},
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate candidate study cards")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("offline", help="Deterministic extraction without LLM")
    po.add_argument(
        "--fangji",
        default=str(DEFAULT_BATCH / "fangji_10p" / "unzipped" / "full.cleaned.md"),
    )
    po.add_argument(
        "--neike",
        default=str(DEFAULT_BATCH / "neike_10p" / "unzipped" / "full.cleaned.md"),
    )
    po.add_argument("--formulas", default="桂枝汤,白虎汤", help="comma-separated formula names")
    po.add_argument("--include-zhongfeng", action="store_true")
    po.add_argument("--batch-id", default="a67c429e-956c-4f28-bec6-69c3b71e17fa")
    po.add_argument(
        "--out",
        default=str(ROOT / "data" / "mineru" / "cards" / "candidates_offline_v1.json"),
    )
    po.add_argument("--review-md")
    po.set_defaults(func=cmd_offline)

    pa = sub.add_parser("api", help="Generate via DashScope/Qwen API")
    pa.add_argument("--input", required=True)
    pa.add_argument("--book", required=True)
    pa.add_argument("--model", default=os.environ.get("QWEN_MODEL", "qwen-plus"))
    pa.add_argument("--max-chars", type=int, default=12000)
    pa.add_argument("--batch-id")
    pa.add_argument(
        "--out",
        default=str(ROOT / "data" / "mineru" / "cards" / "candidates_api_v1.json"),
    )
    pa.add_argument("--review-md")
    pa.set_defaults(func=cmd_api)

    return p


def main() -> None:
    load_env()
    args = build_parser().parse_args()
    args.func(args)
