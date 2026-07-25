"""Jichu / zhenduan candidate-card templates (P5-T02).

Deterministic offline extractors for representative chapters:

- jichu: concept_definition, mechanism, relation, contrast
- zhenduan: four_exam, symptom_syndrome, syndrome, differential

Outputs Candidate Card v2 objects with provenance + content hash when
document_version / chunk metadata are provided.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from tools.document_pipeline.candidate_schema import (
    CARD_TYPE_DEFAULT_RISK,
    CandidateCardV2,
    CandidateSourceV2,
    CandidateStatus,
    RiskLevel,
    compute_content_hash,
    infer_risk,
    resolve_document_key,
)
from tools.document_pipeline.generation import parse_html_tables, stable_id

GENERATOR = "jichu-zhenduan-template-extractor"
PROMPT_VERSION = "p5t02-v1"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
DEFINITION_LINE_RE = re.compile(
    r"^(?P<term>[\u4e00-\u9fffA-Za-z0-9（）()·、]{1,24})"
    r"(?:是|指|即|为)"
    r"(?P<body>.+?)[。．]?$"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _ensure_period(text: str) -> str:
    text = _clean(text)
    if not text:
        return text
    if text[-1] in "。.!！?？；;":
        return text
    return text + "。"


def _strip_enum_prefix(title: str | None) -> str | None:
    if title is None:
        return None
    cleaned = re.sub(r"^[0-9]+[.、．)\s]+", "", _clean(title))
    cleaned = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", cleaned)
    return cleaned or None


def _default_risk(card_type: str) -> tuple[RiskLevel, list[str]]:
    level_name, flags = CARD_TYPE_DEFAULT_RISK.get(card_type, ("medium", ["unclassified_type"]))
    return RiskLevel(level_name), list(flags)


def _heading_context(lines: list[str], line_no: int) -> tuple[str | None, str | None]:
    chapter: str | None = None
    section: str | None = None
    for idx in range(line_no, -1, -1):
        m = HEADING_RE.match(lines[idx])
        if not m:
            continue
        level = len(m.group(1))
        title = _clean(m.group(2))
        if level <= 2 and chapter is None:
            chapter = title
        if level >= 2 and section is None:
            section = title
        if chapter and section:
            break
    return chapter, section


def _iter_sections(md: str) -> list[dict[str, Any]]:
    lines = md.splitlines()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            if current is not None:
                current["end"] = i
                sections.append(current)
            current = {
                "level": len(m.group(1)),
                "title": _clean(m.group(2)),
                "start": i,
                "end": len(lines),
                "line_no": i,
            }
    if current is not None:
        sections.append(current)
    # attach body text
    for sec in sections:
        body_lines = lines[sec["start"] + 1 : sec["end"]]
        # stop body at next same-or-higher heading already handled by end
        sec["body"] = "\n".join(body_lines).strip()
        sec["lines"] = lines
    return sections


def _first_definition_sentence(body: str) -> str | None:
    for raw in body.splitlines():
        line = _clean(raw)
        if not line or line.startswith("#") or line.startswith("<"):
            continue
        if "是" in line or "指" in line or "即" in line:
            # take first sentence-ish
            sentence = re.split(r"[。．]", line)[0]
            return _ensure_period(sentence)
    return None


def _table_spans(md: str) -> list[tuple[int, int, list[list[str]]]]:
    spans: list[tuple[int, int, list[list[str]]]] = []
    for m in re.finditer(r"<table[\s\S]*?</table>", md):
        tables = parse_html_tables(m.group(0))
        if tables:
            spans.append((m.start(), m.end(), tables[0]))
    return spans


def _line_no_for_offset(md: str, offset: int) -> int:
    return md.count("\n", 0, offset)


def _looks_like_header_row(row: list[str]) -> bool:
    if not row:
        return False
    cells = [_clean(c) for c in row if _clean(c)]
    if len(cells) < 2:
        return False
    # Prefer exact header labels; avoid matching content that merely contains 阴/阳.
    exact = {
        "概念",
        "含义",
        "辨证要点",
        "鉴别",
        "鉴别要点",
        "对比",
        "对比项",
        "诊法",
        "表现",
        "表现分析",
        "属性",
        "关系",
        "阴",
        "阳",
    }
    if any(cell in exact for cell in cells):
        return True
    joined = "".join(cells)
    soft_tokens = ("概念", "含义", "辨证要点", "鉴别", "对比项", "诊法", "表现分析")
    return any(tok in joined for tok in soft_tokens)


def _is_relation_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    # 3-col rows like 精与气 / 气能生精 / 气充则精盈
    triple = [r for r in rows if len([c for c in r if c.strip()]) >= 3]
    if len(triple) >= 1 and any(
        "与" in (r[0] if r else "") or "关系" in "".join(r) for r in triple
    ):
        return True
    flat = " ".join(c for r in rows for c in r)
    return (
        any(k in flat for k in ("气能生精", "精能化气", "互根", "互用", "相互")) and len(rows) >= 2
    )


def _is_contrast_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    flat = " ".join(c for r in rows for c in r)
    if "对比" in flat or ("阴" in flat and "阳" in flat and len(rows[0]) >= 3):
        return True
    # two-column pairs that look like A vs B labels in header
    if rows and len(rows[0]) >= 3 and any(h in {"阴", "阳", "左", "右"} for h in rows[0]):
        return True
    return False


def _is_mechanism_table(rows: list[list[str]]) -> bool:
    flat = " ".join(c for r in rows for c in r)
    return any(k in flat for k in ("生理", "病理", "机制", "病机"))


def _is_four_exam_table(rows: list[list[str]]) -> bool:
    names = {(r[0] if r else "").strip() for r in rows}
    return {"望诊", "闻诊", "问诊", "切诊"}.issubset(names) or (
        any("诊法" in (r[0] if r else "") for r in rows[:1])
        and len({"望诊", "闻诊", "问诊", "切诊"} & names) >= 2
    )


def _is_syndrome_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    flat = " ".join(c for r in rows for c in r)
    if "辨证要点" in flat or "证" in flat and "概念" in flat:
        return True
    # first col ends with 证
    data_rows = rows[1:] if _looks_like_header_row(rows[0]) else rows
    hits = sum(1 for r in data_rows if r and str(r[0]).endswith("证"))
    return hits >= 1 and any(len(r) >= 2 for r in data_rows)


def _is_differential_table(rows: list[list[str]]) -> bool:
    flat = " ".join(c for r in rows for c in r)
    return "鉴别" in flat or any(
        "与" in (r[0] if r else "") and "证" in (r[0] if r else "") for r in rows
    )


def _is_symptom_map_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    # two-col tongue/pulse/sign -> syndrome style, without 概念 header
    data = rows[1:] if _looks_like_header_row(rows[0]) else rows
    if not data:
        return False
    if any(len(r) != 2 for r in data if r):
        # allow sparse
        pass
    flat = " ".join(c for r in rows for c in r)
    if any(k in flat for k in ("舌", "脉", "面色", "望")) and "证" in flat:
        return True
    # short two-col map like 淡白舌 / 气血两虚
    short_pairs = [
        r
        for r in data
        if len(r) >= 2 and 1 <= len(_clean(r[0])) <= 12 and 1 <= len(_clean(r[1])) <= 24
    ]
    return len(short_pairs) >= 1 and not _is_four_exam_table(rows) and not _is_syndrome_table(rows)


def build_candidate_v2(
    *,
    book: str,
    document_key: str | None,
    document_version: str,
    chapter: str | None,
    section: str | None,
    card_type: str,
    question: str,
    answer: str,
    source_excerpt: str,
    tags: list[str],
    chunk_id: str,
    pdf_page_index: int = 0,
    printed_page_label: str | None = "1",
    confidence: float = 0.9,
    answer_points: list[str] | None = None,
    status: CandidateStatus = CandidateStatus.GENERATED,
    generator: str = GENERATOR,
    prompt_version: str = PROMPT_VERSION,
    generation_batch_id: str | None = None,
    risk_level: RiskLevel | None = None,
    risk_flags: list[str] | None = None,
) -> CandidateCardV2:
    resolved_key = resolve_document_key(book, document_key=document_key)
    level, flags = _default_risk(card_type)
    if risk_level is not None:
        level = risk_level
    if risk_flags is not None:
        flags = list(risk_flags)
    # keep infer_risk available for review-note overrides later
    _ = infer_risk
    answer_points = answer_points or []
    chunk_ids = [chunk_id]
    content_hash = compute_content_hash(
        document_version=document_version,
        card_type=card_type,
        question=question,
        answer=answer,
        answer_points=answer_points,
        source_excerpt=source_excerpt,
        chunk_ids=chunk_ids,
    )
    source = CandidateSourceV2(
        citation_order=0,
        chunk_id=chunk_id,
        excerpt=source_excerpt,
        pdf_page_index_start=pdf_page_index,
        pdf_page_index_end=pdf_page_index,
        printed_page_start_label=printed_page_label,
        printed_page_end_label=printed_page_label,
    )
    card_id = stable_id(book, section or chapter or card_type, card_type, question)
    return CandidateCardV2(
        id=card_id,
        document_key=resolved_key,
        document_version=document_version,
        book=book,
        chapter=chapter,
        section=section,
        card_type=card_type,
        question=question,
        answer=answer,
        answer_points=answer_points,
        tags=tags,
        source_excerpt=source_excerpt,
        chunk_ids=chunk_ids,
        sources=[source],
        pdf_page_indexes=[pdf_page_index],
        printed_page_labels=[printed_page_label] if printed_page_label else [],
        risk_level=level,
        risk_flags=flags,
        content_hash=content_hash,
        status=status,
        confidence=confidence,
        generator=generator,
        model=None,
        prompt_version=prompt_version,
        generation_batch_id=generation_batch_id,
        input_hash=None,
        created_at=now_iso(),
        reviewer=None,
        reviewed_at=None,
        review_notes=None,
        review_decision=None,
        legacy={
            "schema_version": 1,
            "type": card_type,
            "status": "candidate",
            "template_family": "jichu_zhenduan",
        },
    )


def extract_jichu_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "jichu",
    book: str = "中医基础理论",
    chunk_id_prefix: str = "jichu.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract jichu template cards from cleaned markdown."""
    cards: list[CandidateCardV2] = []
    lines = md.splitlines()
    sections = _iter_sections(md)

    # 1) concept definitions under headings containing 概念/定义
    for sec in sections:
        title = sec["title"]
        body = sec["body"]
        if not any(k in title for k in ("概念", "定义", "含义")) and "基本概念" not in title:
            # also allow plain prose definition right under topic headings like 阴阳的基本概念
            if "概念" not in title:
                continue
        definition = _first_definition_sentence(body)
        if not definition:
            continue
        term = _strip_enum_prefix(title) or title
        term = re.sub(r"(的)?(基本)?(概念|定义|含义)$", "", term)
        term = term or title
        chapter, section = _heading_context(lines, sec["line_no"])
        excerpt = definition
        cards.append(
            build_candidate_v2(
                book=book,
                document_key=document_key,
                document_version=document_version,
                chapter=chapter,
                section=section or title,
                card_type="concept_definition",
                question=f"{term}的基本概念是什么？",
                answer=definition,
                source_excerpt=excerpt,
                tags=[term, "概念"],
                chunk_id=f"{chunk_id_prefix}.concept.{stable_id(term, 'concept')}",
                pdf_page_index=pdf_page_index,
                printed_page_label=printed_page_label,
                confidence=0.91,
                generation_batch_id=generation_batch_id,
            )
        )

    # prose definitions without dedicated heading, e.g. first non-heading sentence
    if not any(c.card_type == "concept_definition" for c in cards):
        for sec in sections:
            definition = _first_definition_sentence(sec["body"])
            if not definition:
                continue
            term = _strip_enum_prefix(sec["title"]) or sec["title"]
            chapter, section = _heading_context(lines, sec["line_no"])
            cards.append(
                build_candidate_v2(
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or sec["title"],
                    card_type="concept_definition",
                    question=f"{term}的基本概念是什么？",
                    answer=definition,
                    source_excerpt=definition,
                    tags=[term, "概念"],
                    chunk_id=f"{chunk_id_prefix}.concept.{stable_id(term, 'concept')}",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    confidence=0.88,
                    generation_batch_id=generation_batch_id,
                )
            )
            break

    # table-driven templates
    for start, _end, rows in _table_spans(md):
        line_no = _line_no_for_offset(md, start)
        chapter, section = _heading_context(lines, line_no)
        data_rows = rows[1:] if _looks_like_header_row(rows[0]) else rows

        if _is_mechanism_table(rows):
            for r in data_rows:
                cells = [c for c in r if _clean(c)]
                if len(cells) < 2:
                    continue
                aspect, meaning = cells[0], cells[1]
                if (
                    aspect not in {"生理", "病理", "病机", "机制"}
                    and "生理" not in aspect
                    and "病理" not in aspect
                ):
                    # still allow labeled mechanism rows
                    if not any(k in aspect for k in ("生理", "病理")):
                        continue
                topic = _strip_enum_prefix(section) or _strip_enum_prefix(chapter) or "本段"
                topic = re.sub(r"(的)?(生理与)?病理机制$", "", topic) or topic
                topic = re.sub(r"(的)?机制$", "", topic) or topic
                cards.append(
                    build_candidate_v2(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section,
                        card_type="mechanism",
                        question=f"{topic}的{aspect}机制是什么？",
                        answer=_ensure_period(meaning),
                        source_excerpt=f"{aspect}：{meaning}",
                        tags=[t for t in [topic, aspect, "机制"] if t],
                        chunk_id=f"{chunk_id_prefix}.mechanism.{stable_id(aspect, meaning)}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
            continue

        if _is_relation_table(rows):
            for r in data_rows:
                cells = [_clean(c) for c in r if _clean(c)]
                if len(cells) >= 3:
                    pair, relation, meaning = cells[0], cells[1], cells[2]
                    q = f"{pair}的关系中，「{relation}」指什么？"
                    ans = _ensure_period(meaning)
                    excerpt = f"{pair} / {relation}：{meaning}"
                    points = [relation, meaning]
                    tags = [pair, "关系"]
                elif len(cells) == 2:
                    relation, meaning = cells[0], cells[1]
                    pair = _strip_enum_prefix(section) or _strip_enum_prefix(chapter) or "相关概念"
                    q = f"{pair}中「{relation}」的含义是什么？"
                    ans = _ensure_period(meaning)
                    excerpt = f"{relation}：{meaning}"
                    points = [relation, meaning]
                    tags = [pair, relation, "关系"]
                else:
                    continue
                cards.append(
                    build_candidate_v2(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section,
                        card_type="relation",
                        question=q,
                        answer=ans,
                        source_excerpt=excerpt,
                        tags=tags,
                        answer_points=points,
                        chunk_id=f"{chunk_id_prefix}.relation.{stable_id(q)}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
            continue

        if _is_contrast_table(rows):
            header = rows[0]
            body = data_rows if data_rows else rows[1:]
            if len(header) >= 3 and body:
                left_name, right_name = header[1], header[2]
                for r in body:
                    cells = [_clean(c) for c in r]
                    if len(cells) < 3:
                        continue
                    dim, left_val, right_val = cells[0], cells[1], cells[2]
                    cards.append(
                        build_candidate_v2(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section,
                            card_type="contrast",
                            question=f"{dim}方面，{left_name}与{right_name}如何对比？",
                            answer=_ensure_period(
                                f"{left_name}：{left_val}；{right_name}：{right_val}"
                            ),
                            source_excerpt=f"{dim} | {left_name}={left_val} | {right_name}={right_val}",
                            tags=[dim, left_name, right_name, "对比"],
                            answer_points=[
                                f"{left_name}：{left_val}",
                                f"{right_name}：{right_val}",
                            ],
                            chunk_id=f"{chunk_id_prefix}.contrast.{stable_id(dim, left_name, right_name)}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
            else:
                # two-col principle contrasts like 对立制约 / 阴阳双方相互抑制
                for r in data_rows:
                    cells = [_clean(c) for c in r if _clean(c)]
                    if len(cells) < 2:
                        continue
                    left, right = cells[0], cells[1]
                    cards.append(
                        build_candidate_v2(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section,
                            card_type="contrast",
                            question=f"「{left}」与相关概念如何理解？",
                            answer=_ensure_period(right),
                            source_excerpt=f"{left}：{right}",
                            tags=[left, "对比"],
                            chunk_id=f"{chunk_id_prefix}.contrast.{stable_id(left, right)}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.86,
                            generation_batch_id=generation_batch_id,
                        )
                    )
            continue

        # two-col principles under 阴阳的基本内容 etc. as relation if not classified
        if data_rows and all(len([c for c in r if _clean(c)]) == 2 for r in data_rows if r):
            flat = " ".join(c for r in rows for c in r)
            if any(k in flat for k in ("对立", "互根", "消长", "转化", "交感")):
                for r in data_rows:
                    cells = [_clean(c) for c in r if _clean(c)]
                    if len(cells) < 2:
                        continue
                    name, meaning = cells[0], cells[1]
                    cards.append(
                        build_candidate_v2(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section,
                            card_type="relation",
                            question=f"阴阳「{name}」的含义是什么？",
                            answer=_ensure_period(meaning),
                            source_excerpt=f"{name}：{meaning}",
                            tags=["阴阳", name, "关系"],
                            chunk_id=f"{chunk_id_prefix}.relation.{stable_id(name, meaning)}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )

    return _dedupe_cards(cards)


def extract_zhenduan_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "zhenduan",
    book: str = "中医诊断学",
    chunk_id_prefix: str = "zhenduan.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract zhenduan template cards from cleaned markdown."""
    cards: list[CandidateCardV2] = []
    lines = md.splitlines()

    for start, _end, rows in _table_spans(md):
        line_no = _line_no_for_offset(md, start)
        chapter, section = _heading_context(lines, line_no)
        data_rows = rows[1:] if _looks_like_header_row(rows[0]) else rows

        if _is_four_exam_table(rows):
            for r in data_rows:
                cells = [_clean(c) for c in r if _clean(c)]
                if len(cells) < 2:
                    continue
                name, meaning = cells[0], cells[1]
                if name not in {"望诊", "闻诊", "问诊", "切诊"}:
                    continue
                cards.append(
                    build_candidate_v2(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or "四诊",
                        card_type="four_exam",
                        question=f"{name}的含义是什么？",
                        answer=_ensure_period(meaning),
                        source_excerpt=f"{name}：{meaning}",
                        tags=["四诊", name],
                        chunk_id=f"{chunk_id_prefix}.four_exam.{stable_id(name)}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.93,
                        generation_batch_id=generation_batch_id,
                    )
                )
            continue

        if _is_differential_table(rows):
            for r in data_rows:
                cells = [_clean(c) for c in r if _clean(c)]
                if len(cells) < 2:
                    continue
                pair, point = cells[0], cells[1]
                if pair in {"证候", "鉴别", "鉴别要点"}:
                    continue
                cards.append(
                    build_candidate_v2(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section,
                        card_type="differential",
                        question=f"{pair}如何鉴别？",
                        answer=_ensure_period(point),
                        source_excerpt=f"{pair}：{point}",
                        tags=[pair, "鉴别"],
                        chunk_id=f"{chunk_id_prefix}.differential.{stable_id(pair)}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
            continue

        if _is_syndrome_table(rows):
            # detect column roles
            header = [_clean(c) for c in rows[0]] if rows else []
            concept_idx = next(
                (i for i, h in enumerate(header) if "概念" in h or "含义" in h),
                1 if len(header) > 1 else None,
            )
            point_idx = next(
                (i for i, h in enumerate(header) if "辨证要点" in h or "要点" in h),
                len(header) - 1 if header else None,
            )
            name_idx = 0
            for r in data_rows:
                cells = [_clean(c) for c in r]
                if not cells:
                    continue
                name = cells[name_idx] if name_idx < len(cells) else ""
                if not name or name in {"证候", "证型"}:
                    continue
                if not name.endswith("证") and "证" not in name:
                    # allow names like 气虚证 already; skip non-syndrome rows
                    if len(name) > 12:
                        continue
                concept = (
                    cells[concept_idx]
                    if concept_idx is not None and concept_idx < len(cells)
                    else (cells[1] if len(cells) > 1 else "")
                )
                points = (
                    cells[point_idx]
                    if point_idx is not None and point_idx < len(cells)
                    else (cells[-1] if cells else "")
                )
                if concept:
                    cards.append(
                        build_candidate_v2(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or name,
                            card_type="syndrome",
                            question=f"{name}的概念是什么？",
                            answer=_ensure_period(concept),
                            source_excerpt=f"{name} 概念：{concept}",
                            tags=[name, "证候", "概念"],
                            chunk_id=f"{chunk_id_prefix}.syndrome.concept.{stable_id(name)}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.91,
                            generation_batch_id=generation_batch_id,
                        )
                    )
                if points and points != concept:
                    cards.append(
                        build_candidate_v2(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or name,
                            card_type="syndrome",
                            question=f"{name}的辨证要点是什么？",
                            answer=_ensure_period(points),
                            source_excerpt=f"{name} 辨证要点：{points}",
                            tags=[name, "证候", "辨证要点"],
                            answer_points=[p for p in re.split(r"[，,；;]", points) if p.strip()],
                            chunk_id=f"{chunk_id_prefix}.syndrome.points.{stable_id(name)}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
            continue

        if _is_symptom_map_table(rows):
            for r in data_rows:
                cells = [_clean(c) for c in r if _clean(c)]
                if len(cells) < 2:
                    continue
                sign, syndrome = cells[0], cells[1]
                if sign in {"诊法", "表现", "舌象"}:
                    continue
                cards.append(
                    build_candidate_v2(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or "舌诊",
                        card_type="symptom_syndrome",
                        question=f"见「{sign}」常见于什么证候？",
                        answer=_ensure_period(syndrome),
                        source_excerpt=f"{sign}：{syndrome}",
                        tags=[sign, syndrome, "映射"],
                        chunk_id=f"{chunk_id_prefix}.symptom_syndrome.{stable_id(sign, syndrome)}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
            continue

    return _dedupe_cards(cards)


def extract_jichu_zhenduan_cards(
    md: str,
    *,
    book_template: str,
    document_version: str,
    generation_batch_id: str | None = None,
    chunk_id_prefix: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Dispatch helper for jichu/zhenduan book templates."""
    key = book_template.strip().lower()
    if key == "jichu":
        return extract_jichu_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "jichu.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key == "zhenduan":
        return extract_zhenduan_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "zhenduan.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    raise ValueError(f"unsupported book_template for P5-T02: {book_template!r}")


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
    "build_candidate_v2",
    "extract_jichu_cards",
    "extract_jichu_zhenduan_cards",
    "extract_zhenduan_cards",
]
