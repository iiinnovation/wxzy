#!/usr/bin/env python3
"""Generate candidate study cards from MinerU cleaned markdown.

Modes:
  - offline: deterministic extraction from formula/disease tables (no API key)
  - api:     call DashScope/Qwen compatible chat API when DASHSCOPE_API_KEY is set

Never prints API keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH = (
    ROOT
    / "data"
    / "mineru"
    / "results"
    / "a67c429e-956c-4f28-bec6-69c3b71e17fa"
)
PROMPT_VERSION = "v1"
SCHEMA_PATH = ROOT / "data" / "mineru" / "cards" / "candidate_card.schema.json"


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
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", parts[-1])[:24].strip("-").lower()
    return f"{slug or 'card'}-{h}"


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
        elif tag == "tr" and self._row:
            self.rows.append(self._row)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def parse_html_tables(md: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for m in re.finditer(r"<table[\s\S]*?</table>", md):
        p = TableParser()
        p.feed(m.group(0))
        if p.rows:
            tables.append(p.rows)
    return tables


def table_to_kv_blocks(rows: list[list[str]]) -> list[dict[str, str]]:
    """Split a formula-style table that may contain multiple named blocks."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    field_keys = {
        "方歌",
        "组成",
        "用法",
        "功用",
        "主治",
        "特点",
        "方解",
        "配伍特点",
        "加减应用",
        "注意事项",
        "注意",
        "概念",
        "病因",
        "病机",
        "辨证要点",
        "治则",
        "治法",
        "代表方",
        "症状",
        "证型",
        "分期",
    }

    for row in rows:
        cells = [c for c in row if c]
        if not cells:
            continue
        # title-only row: single cell name
        if len(cells) == 1 and cells[0] not in field_keys and len(cells[0]) <= 20:
            if current:
                blocks.append(current)
            current = {"_name": cells[0]}
            continue
        if len(cells) == 1 and current is None:
            # colspan title sometimes already handled
            continue
        if len(cells) >= 2:
            key, val = cells[0], cells[1] if len(cells) == 2 else " | ".join(cells[1:])
            # disease stage rows: 分期 证型 症状 治法 代表方
            if len(cells) >= 5 and cells[0] in {"初期", "中期", "中后期", "后期"} or (
                len(cells) >= 5 and current is not None and current.get("_name") and cells[0] not in field_keys
            ):
                # handled by dedicated disease extractor
                if current is None:
                    current = {"_name": "section"}
                stage_key = f"stage::{cells[0]}::{cells[1] if len(cells) > 1 else ''}"
                current[stage_key] = " || ".join(cells)
                continue
            if key in field_keys or (current is not None and len(key) <= 8):
                if current is None:
                    current = {"_name": "unknown"}
                current[key] = val
                continue
            # multi-column disease header/data
            if current is None:
                current = {"_name": cells[0]}
            current["row::" + cells[0]] = " || ".join(cells)
    if current:
        blocks.append(current)
    return blocks


def merge_formula_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge consecutive blocks with same name (e.g. 白虎汤 split across tables)."""
    merged: list[dict[str, str]] = []
    for b in blocks:
        name = b.get("_name")
        if merged and name and merged[-1].get("_name") == name:
            merged[-1].update({k: v for k, v in b.items() if k != "_name"})
        else:
            merged.append(dict(b))
    return merged


def card(
    *,
    book: str,
    chapter: str | None,
    section: str | None,
    ctype: str,
    question: str,
    answer: str,
    excerpt: str,
    tags: list[str],
    source_file: str,
    batch_id: str | None,
    generator: str,
    model: str | None,
    status: str = "candidate",
    confidence: float = 0.9,
    answer_points: list[str] | None = None,
    review_notes: str | None = None,
    source_pages: list[int] | None = None,
    sample_page_idxs: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "id": stable_id(book, section or chapter or "", ctype, question),
        "book": book,
        "chapter": chapter,
        "section": section,
        "type": ctype,
        "question": question,
        "answer": answer,
        "answer_points": answer_points or [],
        "source_excerpt": excerpt,
        "source_pages": source_pages or [],
        "sample_page_idxs": sample_page_idxs or [],
        "tags": tags,
        "status": status,
        "confidence": confidence,
        "review_notes": review_notes,
        "trace": {
            "source_file": source_file,
            "batch_id": batch_id,
            "generator": generator,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "created_at": now_iso(),
        },
    }


def extract_formula_cards(
    md: str,
    *,
    book: str,
    source_file: str,
    batch_id: str | None,
    targets: set[str] | None = None,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    tables = parse_html_tables(md)
    blocks: list[dict[str, str]] = []
    for t in tables:
        blocks.extend(table_to_kv_blocks(t))
    blocks = merge_formula_blocks(blocks)

    for b in blocks:
        name = b.get("_name")
        if not name or name in {"unknown", "section"}:
            continue
        if targets and name not in targets:
            continue
        # only treat as formula if it has formula fields
        if not any(k in b for k in ("组成", "功用", "主治", "方歌")):
            continue

        chapter = "方剂"  # refined below by surrounding headings if needed
        if "组成" in b:
            compose = b["组成"]
            points = re.split(r"\s+", compose.strip())
            cards.append(
                card(
                    book=book,
                    chapter=chapter,
                    section=name,
                    ctype="formula_compose",
                    question=f"{name}的组成是什么？",
                    answer=compose if compose.endswith("。") else compose + "。",
                    excerpt=f"{name} 组成：{compose}",
                    tags=[name, "组成"],
                    source_file=source_file,
                    batch_id=batch_id,
                    generator="offline-extractor",
                    model=None,
                    answer_points=points,
                    confidence=0.92,
                )
            )
        if "功用" in b:
            func = b["功用"]
            cards.append(
                card(
                    book=book,
                    chapter=chapter,
                    section=name,
                    ctype="formula_function",
                    question=f"{name}的功用是什么？",
                    answer=func if func.endswith("。") else func + "。",
                    excerpt=f"{name} 功用：{func}",
                    tags=[name, "功用"],
                    source_file=source_file,
                    batch_id=batch_id,
                    generator="offline-extractor",
                    model=None,
                    confidence=0.9,
                )
            )
        if "主治" in b:
            ind = b["主治"]
            # keep concise first clause if very long
            answer = ind
            status = "candidate"
            conf = 0.85
            if len(ind) > 180:
                status = "needs_review"
                conf = 0.7
                review = "主治原文较长，请人工压缩为可背诵答案，勿改事实。"
            else:
                review = None
            cards.append(
                card(
                    book=book,
                    chapter=chapter,
                    section=name,
                    ctype="formula_indication",
                    question=f"{name}的主治是什么？",
                    answer=answer if answer.endswith("。") else answer + "。",
                    excerpt=f"{name} 主治：{ind}",
                    tags=[name, "主治"],
                    source_file=source_file,
                    batch_id=batch_id,
                    generator="offline-extractor",
                    model=None,
                    status=status,
                    confidence=conf,
                    review_notes=review,
                )
            )
        if "方歌" in b:
            song = b["方歌"]
            cards.append(
                card(
                    book=book,
                    chapter=chapter,
                    section=name,
                    ctype="formula_song",
                    question=f"请默写{name}方歌。",
                    answer=song if song.endswith("。") else song + "。",
                    excerpt=f"{name} 方歌：{song}",
                    tags=[name, "方歌"],
                    source_file=source_file,
                    batch_id=batch_id,
                    generator="offline-extractor",
                    model=None,
                    confidence=0.88,
                )
            )
    return cards


def extract_neike_pulmonary_tb_cards(
    md: str,
    *,
    source_file: str,
    batch_id: str | None,
) -> list[dict[str, Any]]:
    """Targeted extractor for 肺痨 sample section."""
    cards: list[dict[str, Any]] = []
    book = "中医内科学"
    chapter = "肺系病证"
    section = "肺痨"

    # song / selection
    m = re.search(r"【选方】([^\n]+)", md)
    if m:
        text = m.group(1).strip()
        cards.append(
            card(
                book=book,
                chapter=chapter,
                section=section,
                ctype="syndrome_formula",
                question="肺痨各证型对应的选方歌诀是什么？",
                answer=text if text.endswith("。") else text + "。",
                excerpt=f"【选方】{text}",
                tags=["肺痨", "选方", "歌诀"],
                source_file=source_file,
                batch_id=batch_id,
                generator="offline-extractor",
                model=None,
                confidence=0.9,
            )
        )

    # concept from first disease table
    for rows in parse_html_tables(md):
        flat = " ".join(c for r in rows for c in r)
        if "具有传染性的慢性虚弱性疾患" in flat and any(r and r[0] == "概念" for r in rows):
            for r in rows:
                if r and r[0] == "概念":
                    concept = r[-1] if len(r) >= 2 else ""
                    # first sentence only for answer
                    first = re.split(r"[。]", concept)[0] + "。"
                    cards.append(
                        card(
                            book=book,
                            chapter=chapter,
                            section=section,
                            ctype="disease_concept",
                            question="肺痨的概念是什么？",
                            answer=first,
                            excerpt=f"概念：{concept[:220]}",
                            tags=["肺痨", "概念"],
                            source_file=source_file,
                            batch_id=batch_id,
                            generator="offline-extractor",
                            model=None,
                            confidence=0.86,
                        )
                    )
                if r and r[0] == "病机":
                    mech = r[-1]
                    basic = None
                    m2 = re.search(r"【基本病机】([^【]+)", mech)
                    if m2:
                        basic = m2.group(1).strip(" 。;；")
                    if basic:
                        cards.append(
                            card(
                                book=book,
                                chapter=chapter,
                                section=section,
                                ctype="disease_pathogenesis",
                                question="肺痨的基本病机是什么？",
                                answer=basic + "。",
                                excerpt=f"病机：{mech[:220]}",
                                tags=["肺痨", "病机"],
                                source_file=source_file,
                                batch_id=batch_id,
                                generator="offline-extractor",
                                model=None,
                                confidence=0.9,
                            )
                        )
                if r and r[0] == "治则":
                    rule = r[-1]
                    m3 = re.search(r"【治则】([^【]+)", rule)
                    if m3:
                        ans = m3.group(1).strip(" 。;；")
                        cards.append(
                            card(
                                book=book,
                                chapter=chapter,
                                section=section,
                                ctype="treatment_principle",
                                question="肺痨的治则是什么？",
                                answer=ans + "。",
                                excerpt=f"治则：{rule[:220]}",
                                tags=["肺痨", "治则"],
                                source_file=source_file,
                                batch_id=batch_id,
                                generator="offline-extractor",
                                model=None,
                                confidence=0.9,
                            )
                        )
            # stage/syndrome rows
            for r in rows:
                if len(r) >= 5 and r[1] in {"肺阴亏损", "虚火灼肺", "气阴耗伤", "阴阳两虚"}:
                    stage, syndrome, symptoms, method, formula = r[0], r[1], r[2], r[3], r[4]
                    cards.append(
                        card(
                            book=book,
                            chapter=chapter,
                            section=section,
                            ctype="syndrome_formula",
                            question=f"肺痨「{syndrome}」证的治法和代表方是什么？",
                            answer=f"治法：{method}；代表方：{formula}。",
                            excerpt=f"{stage}/{syndrome}：治法={method}；代表方={formula}；症状摘要={symptoms[:80]}",
                            tags=["肺痨", syndrome, "证型", "代表方"],
                            source_file=source_file,
                            batch_id=batch_id,
                            generator="offline-extractor",
                            model=None,
                            answer_points=[f"治法：{method}", f"代表方：{formula}"],
                            confidence=0.91,
                        )
                    )
            break
    return cards


def extract_versioned_zhongfeng_cards(
    md: str,
    *,
    source_file: str,
    batch_id: str | None,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    book = "中医内科学"
    patterns = [
        (r"2\.\s*十版教材分([^\n]+)", "十版教材"),
        (r"3\.\s*人卫三版教材分([^\n]+)", "人卫三版教材"),
        (r"4\.\s*五版教材([^\n]+)", "五版教材"),
    ]
    for pat, ver in patterns:
        m = re.search(pat, md)
        if not m:
            continue
        body = m.group(0).strip()
        cards.append(
            card(
                book=book,
                chapter="脑系病证",
                section="中风",
                ctype="versioned_classification",
                question=f"中风在{ver}中的分期/分类要点是什么？",
                answer=body if body.endswith("。") else body + "。",
                excerpt=body,
                tags=["中风", ver, "分类"],
                source_file=source_file,
                batch_id=batch_id,
                generator="offline-extractor",
                model=None,
                status="needs_review",
                confidence=0.75,
                review_notes="多版本分类，确认未与其他版本混写。",
            )
        )
    return cards


def write_review_md(cards: list[dict[str, Any]], out: Path) -> None:
    lines = [
        "# 候选卡片人工复核清单",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- count: `{len(cards)}`",
        f"- prompt_version: `{PROMPT_VERSION}`",
        "",
        "核对原则：答案必须能在 source_excerpt 找到；剂量/方歌/证型不得改写事实。",
        "",
    ]
    for i, c in enumerate(cards, 1):
        lines.extend(
            [
                f"## {i}. {c['id']}",
                "",
                f"- book/section: `{c.get('book')}` / `{c.get('section')}`",
                f"- type: `{c.get('type')}`",
                f"- status: `{c.get('status')}`  confidence: `{c.get('confidence')}`",
                f"- tags: `{', '.join(c.get('tags') or [])}`",
                "",
                f"**Q:** {c.get('question')}",
                "",
                f"**A:** {c.get('answer')}",
                "",
                f"**excerpt:** {c.get('source_excerpt')}",
                "",
            ]
        )
        if c.get("review_notes"):
            lines.append(f"**notes:** {c['review_notes']}")
            lines.append("")
        lines.append("- [ ] 事实正确")
        lines.append("- [ ] 可直接用于复习 / 需轻微编辑 / 拒绝")
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def call_qwen_api(chunk: str, *, book: str, model: str) -> list[dict[str, Any]]:
    """DashScope compatible OpenAI-style endpoint."""
    import requests

    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY / QWEN_API_KEY not set")

    base = os.environ.get(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).rstrip("/")
    prompt_path = ROOT / "data" / "mineru" / "prompts" / "candidate_cards_v1.md"
    system = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else "输出 JSON 数组卡片。"
    user = f"book={book}\n\n---\n{chunk}\n---\n只输出 JSON 数组。"

    url = f"{base}/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120,
    )
    if resp.status_code >= 400:
        raise SystemExit(f"Qwen API error HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    # strip fences
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    parsed = json.loads(content)
    if not isinstance(parsed, list):
        raise SystemExit("API did not return a JSON array")
    return parsed


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
        source_file=str(fang_path.relative_to(ROOT)) if fang_path.is_relative_to(ROOT) else str(fang_path),
        batch_id=batch_id,
        targets=targets,
    )
    # best-effort chapter from nearby markdown headings
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
            source_file=str(nei_path.relative_to(ROOT)) if nei_path.is_relative_to(ROOT) else str(nei_path),
            batch_id=batch_id,
        )
    )
    if args.include_zhongfeng:
        cards.extend(
            extract_versioned_zhongfeng_cards(
                nei_md,
                source_file=str(nei_path.relative_to(ROOT)) if nei_path.is_relative_to(ROOT) else str(nei_path),
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
    out_md = Path(args.review_md).expanduser().resolve() if args.review_md else out_json.with_suffix(".REVIEW.md")
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
    # keep prompt context bounded
    chunk = md[: args.max_chars]
    cards = call_qwen_api(chunk, book=args.book, model=args.model)
    # normalize trace
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
    out_md = Path(args.review_md).expanduser().resolve() if args.review_md else out_json.with_suffix(".REVIEW.md")
    write_review_md(cards, out_md)
    print(json.dumps({"count": len(cards), "out": str(out_json), "review_md": str(out_md)}, ensure_ascii=False, indent=2))


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


if __name__ == "__main__":
    main()
