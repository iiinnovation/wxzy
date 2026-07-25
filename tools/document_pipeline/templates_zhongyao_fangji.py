"""Zhongyao / fangji candidate-card templates (P5-T03).

Deterministic offline extractors for representative chapters:

- zhongyao: herb_nature_flavor, herb_function, herb_indication,
  herb_usage, herb_toxicity_caution, herb_compatibility, herb_contrast
- fangji: formula_compose, formula_function, formula_indication,
  formula_song, formula_usage_note, formula_compatibility

Outputs Candidate Card v2 objects with provenance + content hash.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from tools.document_pipeline.candidate_schema import CandidateCardV2, CandidateStatus
from tools.document_pipeline.generation import (
    merge_formula_blocks,
    parse_html_tables,
    table_to_kv_blocks,
)
from tools.document_pipeline.templates_jichu_zhenduan import build_candidate_v2

GENERATOR = "zhongyao-fangji-template-extractor"
PROMPT_VERSION = "p5t03-v1"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_RE = re.compile(r"<table[\s\S]*?</table>")

HERB_FIELD_TO_CARD: dict[str, tuple[str, str]] = {
    "性味归经": ("herb_nature_flavor", "性味归经"),
    "功效": ("herb_function", "功效"),
    "主治": ("herb_indication", "主治"),
    "用法用量": ("herb_usage", "用法用量"),
    "用法": ("herb_usage", "用法"),
    "注意事项": ("herb_toxicity_caution", "注意事项"),
    "注意": ("herb_toxicity_caution", "注意事项"),
    "禁忌": ("herb_toxicity_caution", "禁忌"),
    "毒性": ("herb_toxicity_caution", "毒性"),
    "配伍": ("herb_compatibility", "配伍"),
}

FORMULA_FIELD_TO_CARD: dict[str, tuple[str, str, str]] = {
    # field -> (card_type, question_suffix, tag)
    "组成": ("formula_compose", "的组成是什么？", "组成"),
    "功用": ("formula_function", "的功用是什么？", "功用"),
    "主治": ("formula_indication", "的主治是什么？", "主治"),
    "方歌": ("formula_song", "方歌。", "方歌"),  # special question below
    "用法": ("formula_usage_note", "的用法是什么？", "用法"),
    "注意事项": ("formula_usage_note", "的注意事项是什么？", "注意事项"),
    "注意": ("formula_usage_note", "的注意事项是什么？", "注意事项"),
    "配伍特点": ("formula_compatibility", "的配伍特点是什么？", "配伍特点"),
    "配伍": ("formula_compatibility", "的配伍意义是什么？", "配伍"),
    "方解": ("formula_compatibility", "的配伍（方解）要点是什么？", "方解"),
}

TOXICITY_HINT_RE = re.compile(r"(有毒|有小毒|大毒|禁用|忌|慎用|禁忌|毒性)")
HERB_NAME_CLEAN_RE = re.compile(r"[*＊★※]+")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _ensure_period(text: str) -> str:
    text = _clean(text)
    if not text:
        return text
    if text[-1] in "。.!！?？；;":
        return text
    return text + "。"


def _strip_herb_markers(name: str) -> str:
    cleaned = HERB_NAME_CLEAN_RE.sub("", _clean(name))
    return cleaned or _clean(name)


def _heading_stack(md: str) -> list[dict[str, Any]]:
    lines = md.splitlines()
    headings: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        headings.append(
            {
                "level": len(m.group(1)),
                "title": _clean(m.group(2)),
                "line_no": i,
                "char_offset": sum(len(x) + 1 for x in lines[:i]),
            }
        )
    return headings


def _context_at(headings: list[dict[str, Any]], char_offset: int) -> tuple[str | None, str | None, str | None]:
    chapter: str | None = None
    section: str | None = None
    nearest: str | None = None
    for h in headings:
        if h["char_offset"] > char_offset:
            break
        title = h["title"]
        nearest = title
        if h["level"] <= 2:
            chapter = title
        if h["level"] >= 2:
            section = title
    return chapter, section, nearest


def _is_header_row(row: list[str], keywords: set[str]) -> bool:
    joined = "".join(_clean(c) for c in row)
    return any(k in joined for k in keywords)


def _looks_like_herb_inventory(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    header = [_clean(c) for c in rows[0]]
    joined = "".join(header)
    if not any(k in joined for k in ("中药名", "药名", "药物")):
        return False
    return any(k in joined for k in ("性味", "功效", "主治", "用法", "注意"))


def _looks_like_contrast(rows: list[list[str]]) -> bool:
    if len(rows) < 2 or len(rows[0]) < 3:
        return False
    # inventory multi-col tables are not contrasts
    if _looks_like_herb_inventory(rows):
        return False
    header = [_clean(c) for c in rows[0]]
    if any(k in header[0] for k in ("对比", "比较", "鉴别", "项目", "对比项")):
        return True
    # first col short labels, other cols look like entity names (not field headers)
    fieldish = ("性味", "功效", "主治", "用法", "注意", "中药", "药名")
    if any(any(f in h for f in fieldish) for h in header):
        return False
    return len(header[0]) <= 6 and all(1 <= len(c) <= 12 for c in header[1:])


def _looks_like_herb_kv(rows: list[list[str]]) -> bool:
    keys = {_clean(r[0]) for r in rows if len(r) >= 2}
    return bool(keys & set(HERB_FIELD_TO_CARD))


def _compose_points(compose: str) -> list[str]:
    parts = [p for p in re.split(r"[\s,，、;；]+", _clean(compose)) if p]
    return parts


def _make_card(
    *,
    book: str,
    document_key: str,
    document_version: str,
    chapter: str | None,
    section: str | None,
    card_type: str,
    question: str,
    answer: str,
    source_excerpt: str,
    tags: list[str],
    chunk_id: str,
    pdf_page_index: int,
    printed_page_label: str | None,
    confidence: float,
    generation_batch_id: str | None,
    answer_points: list[str] | None = None,
    status: CandidateStatus = CandidateStatus.GENERATED,
) -> CandidateCardV2:
    card = build_candidate_v2(
        book=book,
        document_key=document_key,
        document_version=document_version,
        chapter=chapter,
        section=section,
        card_type=card_type,
        question=question,
        answer=_ensure_period(answer),
        source_excerpt=source_excerpt,
        tags=tags,
        chunk_id=chunk_id,
        pdf_page_index=pdf_page_index,
        printed_page_label=printed_page_label,
        confidence=confidence,
        answer_points=answer_points,
        status=status,
        generator=GENERATOR,
        prompt_version=PROMPT_VERSION,
        generation_batch_id=generation_batch_id,
    )
    # stamp template family without dropping other legacy fields
    legacy = dict(card.legacy or {})
    legacy["template_family"] = "zhongyao_fangji"
    legacy["schema_version"] = 1
    legacy["type"] = card_type
    legacy["status"] = "candidate"
    return card.model_copy(update={"legacy": legacy})


def _emit_herb_field_card(
    *,
    herb_name: str,
    field_key: str,
    field_value: str,
    book: str,
    document_key: str,
    document_version: str,
    chapter: str | None,
    section: str | None,
    chunk_id: str,
    pdf_page_index: int,
    printed_page_label: str | None,
    generation_batch_id: str | None,
) -> CandidateCardV2 | None:
    mapping = HERB_FIELD_TO_CARD.get(field_key)
    if mapping is None:
        # toxicity cues inside unlabeled caution-like fields
        if TOXICITY_HINT_RE.search(field_key) or TOXICITY_HINT_RE.search(field_value):
            card_type, label = "herb_toxicity_caution", field_key or "注意事项"
        else:
            return None
    else:
        card_type, label = mapping

    value = _clean(field_value)
    if not value:
        return None

    display_name = _strip_herb_markers(herb_name)
    if card_type == "herb_nature_flavor":
        question = f"{display_name}的性味归经是什么？"
    elif card_type == "herb_function":
        question = f"{display_name}的功效是什么？"
    elif card_type == "herb_indication":
        question = f"{display_name}的主治是什么？"
    elif card_type == "herb_usage":
        question = f"{display_name}的用法用量是什么？"
    elif card_type == "herb_toxicity_caution":
        question = f"{display_name}的{label}是什么？"
    elif card_type == "herb_compatibility":
        question = f"{display_name}的配伍要点是什么？"
    else:
        question = f"{display_name}的{label}是什么？"

    conf = 0.9
    status = CandidateStatus.GENERATED
    if card_type in {"herb_usage", "herb_toxicity_caution"}:
        conf = 0.88
    if card_type == "herb_indication" and len(value) > 180:
        status = CandidateStatus.NEEDS_REVIEW
        conf = 0.7

    return _make_card(
        book=book,
        document_key=document_key,
        document_version=document_version,
        chapter=chapter,
        section=section or display_name,
        card_type=card_type,
        question=question,
        answer=value,
        source_excerpt=f"{display_name} {label}：{value}",
        tags=[display_name, label],
        chunk_id=chunk_id,
        pdf_page_index=pdf_page_index,
        printed_page_label=printed_page_label,
        confidence=conf,
        generation_batch_id=generation_batch_id,
        status=status,
    )


def _extract_herb_kv_cards(
    rows: list[list[str]],
    *,
    herb_name: str,
    book: str,
    document_key: str,
    document_version: str,
    chapter: str | None,
    section: str | None,
    chunk_id: str,
    pdf_page_index: int,
    printed_page_label: str | None,
    generation_batch_id: str | None,
) -> list[CandidateCardV2]:
    cards: list[CandidateCardV2] = []
    for row in rows:
        if len(row) < 2:
            continue
        key = _clean(row[0])
        val = _clean(" | ".join(row[1:]))
        card = _emit_herb_field_card(
            herb_name=herb_name,
            field_key=key,
            field_value=val,
            book=book,
            document_key=document_key,
            document_version=document_version,
            chapter=chapter,
            section=section,
            chunk_id=chunk_id,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
            generation_batch_id=generation_batch_id,
        )
        if card is not None:
            cards.append(card)
    return cards


def _extract_herb_inventory_cards(
    rows: list[list[str]],
    *,
    book: str,
    document_key: str,
    document_version: str,
    chapter: str | None,
    section: str | None,
    chunk_id_prefix: str,
    table_idx: int,
    pdf_page_index: int,
    printed_page_label: str | None,
    generation_batch_id: str | None,
) -> list[CandidateCardV2]:
    header = [_clean(c) for c in rows[0]]
    # map header labels to canonical field keys
    col_map: dict[int, str] = {}
    name_col: int | None = None
    for i, h in enumerate(header):
        if any(k in h for k in ("中药名", "药名", "药物")) and "对比" not in h:
            name_col = i
            continue
        for canon in HERB_FIELD_TO_CARD:
            if canon in h or (canon == "性味归经" and "性味" in h):
                col_map[i] = canon
                break
            if canon == "用法用量" and h in {"用法", "用量", "剂量"}:
                col_map[i] = "用法用量"
                break
            if canon == "注意事项" and any(x in h for x in ("注意", "禁忌", "毒性")):
                col_map[i] = "注意事项"
                break

    if name_col is None:
        return []

    cards: list[CandidateCardV2] = []
    for r_i, row in enumerate(rows[1:], start=1):
        if name_col >= len(row):
            continue
        raw_name = _clean(row[name_col])
        if not raw_name:
            continue
        # auto-mark toxicity when name has * or 有毒 cues in any cell
        row_text = " ".join(_clean(c) for c in row)
        for c_i, field_key in col_map.items():
            if c_i >= len(row):
                continue
            val = _clean(row[c_i])
            if not val:
                continue
            # promote toxic content even if column is 性味归经 containing 有小毒
            effective_key = field_key
            if field_key == "性味归经" and TOXICITY_HINT_RE.search(val):
                # still emit nature/flavor, and also a toxicity card from the toxic cue
                nature_card = _emit_herb_field_card(
                    herb_name=raw_name,
                    field_key="性味归经",
                    field_value=val,
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or _strip_herb_markers(raw_name),
                    chunk_id=f"{chunk_id_prefix}.inv.{table_idx}.{r_i}.nature",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    generation_batch_id=generation_batch_id,
                )
                if nature_card is not None:
                    cards.append(nature_card)
                tox_card = _emit_herb_field_card(
                    herb_name=raw_name,
                    field_key="毒性",
                    field_value=val,
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or _strip_herb_markers(raw_name),
                    chunk_id=f"{chunk_id_prefix}.inv.{table_idx}.{r_i}.tox",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    generation_batch_id=generation_batch_id,
                )
                if tox_card is not None:
                    cards.append(tox_card)
                continue

            card = _emit_herb_field_card(
                herb_name=raw_name,
                field_key=effective_key,
                field_value=val,
                book=book,
                document_key=document_key,
                document_version=document_version,
                chapter=chapter,
                section=section or _strip_herb_markers(raw_name),
                chunk_id=f"{chunk_id_prefix}.inv.{table_idx}.{r_i}.{c_i}",
                pdf_page_index=pdf_page_index,
                printed_page_label=printed_page_label,
                generation_batch_id=generation_batch_id,
            )
            if card is not None:
                cards.append(card)

        # if only marker * and no dedicated caution column value, still flag name-level caution
        if ("*" in raw_name or "＊" in raw_name) and not any(
            c.card_type == "herb_toxicity_caution"
            and _strip_herb_markers(raw_name) in (c.section or "")
            for c in cards[-8:]
        ):
            if TOXICITY_HINT_RE.search(row_text):
                # already covered via fields
                pass
    return cards


def _extract_herb_contrast_cards(
    rows: list[list[str]],
    *,
    book: str,
    document_key: str,
    document_version: str,
    chapter: str | None,
    section: str | None,
    chunk_id: str,
    pdf_page_index: int,
    printed_page_label: str | None,
    generation_batch_id: str | None,
) -> list[CandidateCardV2]:
    header = [_clean(c) for c in rows[0]]
    entities = [h for h in header[1:] if h]
    if len(entities) < 2:
        return []

    lines: list[str] = []
    for row in rows[1:]:
        if not row:
            continue
        label = _clean(row[0]) if row else ""
        values = [_clean(row[i]) if i < len(row) else "" for i in range(1, len(header))]
        if not label and not any(values):
            continue
        pair_bits = []
        for ent, val in zip(entities, values, strict=False):
            if val:
                pair_bits.append(f"{ent}：{val}")
        if pair_bits:
            lines.append(f"{label} — " + "；".join(pair_bits) if label else "；".join(pair_bits))

    if not lines:
        return []

    left, right = entities[0], entities[1]
    answer = "；".join(lines)
    question = f"{left}与{right}有何区别？"
    return [
        _make_card(
            book=book,
            document_key=document_key,
            document_version=document_version,
            chapter=chapter,
            section=section or f"{left}/{right}",
            card_type="herb_contrast",
            question=question,
            answer=answer,
            source_excerpt=f"{left} vs {right}：{answer}",
            tags=[left, right, "对比"],
            chunk_id=chunk_id,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
            confidence=0.9,
            generation_batch_id=generation_batch_id,
        )
    ]


def extract_zhongyao_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "zhongyao",
    book: str = "中药学",
    chunk_id_prefix: str = "zhongyao.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract zhongyao template cards from cleaned markdown."""
    headings = _heading_stack(md)
    cards: list[CandidateCardV2] = []

    for t_i, match in enumerate(TABLE_RE.finditer(md)):
        tables = parse_html_tables(match.group(0))
        if not tables:
            continue
        rows = tables[0]
        chapter, section, nearest = _context_at(headings, match.start())
        herb_name = nearest or section or "未知中药"
        # prefer deeper heading as herb entry name when it looks like a drug name
        if nearest and len(nearest) <= 12 and not any(
            k in nearest for k in ("章", "节", "对比", "常用", "相似")
        ):
            herb_name = nearest

        chunk_base = f"{chunk_id_prefix}.t{t_i}"

        if _looks_like_herb_inventory(rows):
            cards.extend(
                _extract_herb_inventory_cards(
                    rows,
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section,
                    chunk_id_prefix=chunk_id_prefix,
                    table_idx=t_i,
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    generation_batch_id=generation_batch_id,
                )
            )
            continue

        if _looks_like_contrast(rows):
            cards.extend(
                _extract_herb_contrast_cards(
                    rows,
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section,
                    chunk_id=f"{chunk_base}.contrast",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    generation_batch_id=generation_batch_id,
                )
            )
            continue

        if _looks_like_herb_kv(rows):
            cards.extend(
                _extract_herb_kv_cards(
                    rows,
                    herb_name=herb_name,
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or _strip_herb_markers(herb_name),
                    chunk_id=f"{chunk_base}.kv",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    generation_batch_id=generation_batch_id,
                )
            )
            continue

    return _dedupe_cards(cards)


def _formula_question(name: str, field: str, suffix: str) -> str:
    if field == "方歌":
        return f"请默写{name}方歌。"
    return f"{name}{suffix}"


def extract_fangji_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "fangji",
    book: str = "方剂学",
    chunk_id_prefix: str = "fangji.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
    targets: set[str] | None = None,
) -> list[CandidateCardV2]:
    """Extract fangji template cards from cleaned markdown (v2)."""
    headings = _heading_stack(md)
    # chapter from first suitable heading if blocks lack context
    default_chapter = None
    for h in headings:
        if h["level"] <= 2:
            default_chapter = h["title"]
            break

    tables = parse_html_tables(md)
    blocks: list[dict[str, str]] = []
    for t in tables:
        blocks.extend(table_to_kv_blocks(t))
    blocks = merge_formula_blocks(blocks)

    cards: list[CandidateCardV2] = []
    for b_i, block in enumerate(blocks):
        name = _clean(block.get("_name", ""))
        if not name or name in {"unknown", "section"}:
            continue
        if targets and name not in targets:
            continue
        if not any(k in block for k in FORMULA_FIELD_TO_CARD):
            continue

        # try to find a heading context near this formula name in md
        chapter = default_chapter or "方剂"
        section = name
        # scan headings that mention formula chapter keywords after previous
        for h in headings:
            if name in h["title"]:
                section = h["title"]
            if h["level"] <= 2 and any(k in h["title"] for k in ("章", "剂", "方剂")):
                # keep latest chapter-like heading before we can't order precisely
                chapter = h["title"]

        for field, (card_type, q_suffix, tag) in FORMULA_FIELD_TO_CARD.items():
            if field not in block:
                continue
            value = _clean(block[field])
            if not value:
                continue

            conf = 0.9
            status = CandidateStatus.GENERATED
            answer_points: list[str] | None = None
            if card_type == "formula_compose":
                conf = 0.92
                answer_points = _compose_points(value)
            elif card_type == "formula_song":
                conf = 0.88
            elif card_type == "formula_usage_note":
                conf = 0.88
            elif card_type == "formula_indication" and len(value) > 180:
                status = CandidateStatus.NEEDS_REVIEW
                conf = 0.7

            cards.append(
                _make_card(
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section,
                    card_type=card_type,
                    question=_formula_question(name, field, q_suffix),
                    answer=value,
                    source_excerpt=f"{name} {tag}：{value}",
                    tags=[name, tag],
                    chunk_id=f"{chunk_id_prefix}.f{b_i}.{field}",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    confidence=conf,
                    generation_batch_id=generation_batch_id,
                    answer_points=answer_points,
                    status=status,
                )
            )

    return _dedupe_cards(cards)


def extract_zhongyao_fangji_cards(
    md: str,
    *,
    book_template: str,
    document_version: str,
    generation_batch_id: str | None = None,
    chunk_id_prefix: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Dispatch helper for zhongyao/fangji book templates."""
    key = book_template.strip().lower()
    if key == "zhongyao":
        return extract_zhongyao_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "zhongyao.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key == "fangji":
        return extract_fangji_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "fangji.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    raise ValueError(f"unsupported book_template for P5-T03: {book_template!r}")


def _dedupe_cards(cards: Iterable[CandidateCardV2]) -> list[CandidateCardV2]:
    out: list[CandidateCardV2] = []
    seen: set[str] = set()
    for card in cards:
        key = card.content_hash
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


__all__ = [
    "GENERATOR",
    "PROMPT_VERSION",
    "extract_fangji_cards",
    "extract_zhongyao_cards",
    "extract_zhongyao_fangji_cards",
]
