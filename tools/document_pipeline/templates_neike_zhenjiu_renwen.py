"""Neike / zhenjiu / renwen candidate-card templates (P5-T04).

Deterministic offline extractors for representative chapters:

- neike: disease_concept, disease_pathogenesis, treatment_principle,
  syndrome_formula, versioned_classification
- zhenjiu: meridian_overview, acupoint_location, acupoint_indication,
  acupoint_operation, acupoint_caution
- renwen: ethics_principle, regulation_fact, ethics_scenario, history_fact

Outputs Candidate Card v2 objects with provenance + content hash.
Version-sensitive regulation / multi-version classification cards carry
high/critical risk and keep explicit version cues in tags/answer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from tools.document_pipeline.candidate_schema import CandidateCardV2, CandidateStatus
from tools.document_pipeline.generation import parse_html_tables
from tools.document_pipeline.templates_jichu_zhenduan import build_candidate_v2

GENERATOR = "neike-zhenjiu-renwen-template-extractor"
PROMPT_VERSION = "p5t04-v1"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_RE = re.compile(r"<table[\s\S]*?</table>")
BRACKET_FIELD_RE = re.compile(r"【(?P<key>[^】]{1,12})】(?P<val>[^【\n]+)")
VERSIONED_LINE_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:\d+[.、．)\s]+)?(?P<label>(?:十版|十一版|九版|八版|七版|五版|人卫三版)教材)(?P<body>.+)$"
)
DATE_RE = re.compile(r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|20\d{2}\s*年)")
STATUTE_RE = re.compile(r"《[^》]{2,40}(?:法|条例|办法|规范|准则)》")
ETHICS_PRINCIPLE_KEYS = ("不伤害", "有利", "尊重", "公正", "知情同意", "行善")
ACUPOINT_CAUTION_RE = re.compile(r"(孕妇|禁|慎|不可深刺|伤及|忌|不宜|排尿后|深刺)")
HISTORY_HINT_RE = re.compile(r"(首见|最早|出自|记载|沿革|《[^》]+》)")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _ensure_period(text: str) -> str:
    text = _clean(text)
    if not text:
        return text
    if text[-1] in "。.!！?？；;":
        return text
    return text + "。"


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


def _context_at(
    headings: list[dict[str, Any]], char_offset: int
) -> tuple[str | None, str | None, str | None]:
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


def _disease_name(section: str | None, chapter: str | None) -> str:
    for title in (section, chapter):
        if not title:
            continue
        cleaned = re.sub(r"^[0-9]+[.、．)\s]+", "", title)
        cleaned = re.sub(r"第[一二三四五六七八九十百零0-9]+[章节]\s*", "", cleaned)
        cleaned = cleaned.split("|")[-1].strip()
        # drop long chapter wrappers
        if 1 <= len(cleaned) <= 12 and not any(k in cleaned for k in ("病证", "总论", "系统")):
            return cleaned
        # e.g. 第六节 肺痨
        m = re.search(r"([\u4e00-\u9fff]{1,8})$", cleaned)
        if m and m.group(1) not in {"病证", "总论"}:
            return m.group(1)
    return section or chapter or "本病"


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
    review_notes: str | None = None,
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
    legacy = dict(card.legacy or {})
    legacy["template_family"] = "neike_zhenjiu_renwen"
    legacy["schema_version"] = 1
    legacy["type"] = card_type
    legacy["status"] = "candidate"
    updates: dict[str, Any] = {"legacy": legacy}
    if review_notes:
        updates["review_notes"] = review_notes
    return card.model_copy(update=updates)


def _dedupe_cards(cards: Iterable[CandidateCardV2]) -> list[CandidateCardV2]:
    out: list[CandidateCardV2] = []
    seen: set[str] = set()
    for card in cards:
        if card.content_hash in seen:
            continue
        seen.add(card.content_hash)
        out.append(card)
    return out


def _looks_like_syndrome_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    header = "".join(_clean(c) for c in rows[0])
    return ("证型" in header or "证候" in header) and (
        "治法" in header or "代表方" in header or "方药" in header
    )


def _looks_like_disease_kv(rows: list[list[str]]) -> bool:
    keys = {_clean(r[0]) for r in rows if r}
    return bool(keys & {"概念", "病机", "病因", "治则", "治法", "辨证要点"})


def _looks_like_acupoint_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    header = "".join(_clean(c) for c in rows[0])
    return any(k in header for k in ("穴位", "腧穴", "穴名")) and any(
        k in header for k in ("定位", "主治", "刺灸", "操作")
    )


def _header_index_map(header: list[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, int]:
    out: dict[str, int] = {}
    cleaned = [_clean(h) for h in header]
    for canon, keys in aliases.items():
        for i, h in enumerate(cleaned):
            if any(k in h for k in keys):
                out[canon] = i
                break
    return out


def extract_neike_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "neike",
    book: str = "中医内科学",
    chunk_id_prefix: str = "neike.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract neike template cards from cleaned markdown."""
    headings = _heading_stack(md)
    cards: list[CandidateCardV2] = []

    # prose bracket fields and disease intro lines under headings
    lines = md.splitlines()
    for i, raw in enumerate(lines):
        line = _clean(raw)
        if not line or HEADING_RE.match(raw):
            continue
        chapter, section, _ = _context_at(headings, sum(len(x) + 1 for x in lines[:i]))
        disease = _disease_name(section, chapter)

        if line.startswith("【选方】"):
            body = _clean(line[len("【选方】") :])
            if body:
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or disease,
                        card_type="syndrome_formula",
                        question=f"{disease}各证型对应的选方歌诀是什么？",
                        answer=body,
                        source_excerpt=f"【选方】{body}",
                        tags=[disease, "选方", "歌诀"],
                        chunk_id=f"{chunk_id_prefix}.xuanfang.{i}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )

        # versioned classification lines
        vm = VERSIONED_LINE_RE.match(line) or VERSIONED_LINE_RE.match(
            re.sub(r"^#+\s*", "", raw).strip()
        )
        if vm and (
            "分" in vm.group("body") or "中经络" in vm.group("body") or "中脏腑" in vm.group("body")
        ):
            label = vm.group("label")
            body = _clean(vm.group(0))
            # include following non-heading prose line if it elaborates
            if i + 1 < len(lines):
                nxt = _clean(lines[i + 1])
                if (
                    nxt
                    and not HEADING_RE.match(lines[i + 1])
                    and label in nxt
                    or (
                        nxt
                        and not HEADING_RE.match(lines[i + 1])
                        and len(nxt) > 8
                        and "教材" not in nxt[:4]
                    )
                ):
                    if label.split("教材")[0] in nxt or "中经络" in nxt or "中脏腑" in nxt:
                        body = _clean(body + " " + nxt)
            cards.append(
                _make_card(
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter or "脑系病证",
                    section=section or "中风",
                    card_type="versioned_classification",
                    question=f"中风在{label}中的分期/分类要点是什么？",
                    answer=body,
                    source_excerpt=body,
                    tags=["中风", label, "分类", "multi_version"],
                    chunk_id=f"{chunk_id_prefix}.version.{i}",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    confidence=0.75,
                    generation_batch_id=generation_batch_id,
                    status=CandidateStatus.NEEDS_REVIEW,
                    review_notes="多版本分类，确认未与其他版本混写。",
                )
            )

        # short disease concept prose under disease heading
        if (
            section
            and len(line) >= 12
            and any(k in line for k in ("是", "指"))
            and any(k in line for k in ("病", "证", "疾患", "特征"))
            and not line.startswith("【")
        ):
            # only first-definition-like lines near disease heading
            if disease in line or "传染" in line or "以" in line:
                # avoid version lines
                if "教材" not in line:
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section,
                            card_type="disease_concept",
                            question=f"{disease}的概念是什么？",
                            answer=line,
                            source_excerpt=line,
                            tags=[disease, "概念"],
                            chunk_id=f"{chunk_id_prefix}.concept.prose.{i}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.84,
                            generation_batch_id=generation_batch_id,
                        )
                    )

    # tables
    for t_i, match in enumerate(TABLE_RE.finditer(md)):
        tables = parse_html_tables(match.group(0))
        if not tables:
            continue
        rows = tables[0]
        chapter, section, _ = _context_at(headings, match.start())
        disease = _disease_name(section, chapter)
        chunk_base = f"{chunk_id_prefix}.t{t_i}"

        if _looks_like_disease_kv(rows):
            for r_i, row in enumerate(rows):
                if len(row) < 2:
                    continue
                key = _clean(row[0])
                val = _clean(" ".join(row[1:]))
                if not val:
                    continue
                if key == "概念":
                    first = re.split(r"[。]", val)[0]
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or disease,
                            card_type="disease_concept",
                            question=f"{disease}的概念是什么？",
                            answer=first,
                            source_excerpt=f"概念：{val[:220]}",
                            tags=[disease, "概念"],
                            chunk_id=f"{chunk_base}.concept",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.88,
                            generation_batch_id=generation_batch_id,
                        )
                    )
                elif key in {"病机", "病因病机"}:
                    basic = None
                    m2 = re.search(r"【基本病机】([^【]+)", val)
                    if m2:
                        basic = _clean(m2.group(1).strip(" 。;；"))
                    ans = basic or val
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or disease,
                            card_type="disease_pathogenesis",
                            question=f"{disease}的基本病机是什么？",
                            answer=ans,
                            source_excerpt=f"病机：{val[:220]}",
                            tags=[disease, "病机"],
                            chunk_id=f"{chunk_base}.pathogenesis",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
                elif key == "治则" or (key == "治法" and "【治则】" in val):
                    m3 = re.search(r"【治则】([^【]+)", val)
                    ans = _clean(m3.group(1)) if m3 else val
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or disease,
                            card_type="treatment_principle",
                            question=f"{disease}的治则是什么？",
                            answer=ans,
                            source_excerpt=f"治则：{val[:220]}",
                            tags=[disease, "治则"],
                            chunk_id=f"{chunk_base}.principle",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
            continue

        if _looks_like_syndrome_table(rows):
            header = [_clean(c) for c in rows[0]]
            col = _header_index_map(
                header,
                {
                    "syndrome": ("证型", "证候"),
                    "method": ("治法",),
                    "formula": ("代表方", "方药", "选方"),
                    "symptoms": ("症状", "临床表现"),
                    "stage": ("分期", "阶段"),
                },
            )
            if "syndrome" not in col:
                continue
            for r_i, row in enumerate(rows[1:], start=1):
                syn = _clean(row[col["syndrome"]]) if col["syndrome"] < len(row) else ""
                if not syn:
                    continue
                method = (
                    _clean(row[col["method"]])
                    if "method" in col and col["method"] < len(row)
                    else ""
                )
                formula = (
                    _clean(row[col["formula"]])
                    if "formula" in col and col["formula"] < len(row)
                    else ""
                )
                symptoms = (
                    _clean(row[col["symptoms"]])
                    if "symptoms" in col and col["symptoms"] < len(row)
                    else ""
                )
                stage = (
                    _clean(row[col["stage"]]) if "stage" in col and col["stage"] < len(row) else ""
                )
                if not (method or formula):
                    continue
                answer_bits = []
                points = []
                if method:
                    answer_bits.append(f"治法：{method}")
                    points.append(f"治法：{method}")
                if formula:
                    answer_bits.append(f"代表方：{formula}")
                    points.append(f"代表方：{formula}")
                excerpt_bits = [f"{stage + '/' if stage else ''}{syn}"]
                if method:
                    excerpt_bits.append(f"治法={method}")
                if formula:
                    excerpt_bits.append(f"代表方={formula}")
                if symptoms:
                    excerpt_bits.append(f"症状摘要={symptoms[:80]}")
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or disease,
                        card_type="syndrome_formula",
                        question=f"{disease}「{syn}」证的治法和代表方是什么？",
                        answer="；".join(answer_bits),
                        source_excerpt="；".join(excerpt_bits),
                        tags=[disease, syn, "证型", "代表方"],
                        chunk_id=f"{chunk_base}.syndrome.{r_i}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.91,
                        generation_batch_id=generation_batch_id,
                        answer_points=points,
                    )
                )
            continue

    return _dedupe_cards(cards)


def extract_zhenjiu_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "zhenjiu",
    book: str = "针灸学",
    chunk_id_prefix: str = "zhenjiu.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract zhenjiu template cards from cleaned markdown."""
    headings = _heading_stack(md)
    cards: list[CandidateCardV2] = []
    lines = md.splitlines()

    # meridian / system overview prose
    for i, raw in enumerate(lines):
        if HEADING_RE.match(raw):
            continue
        line = _clean(raw)
        if not line:
            continue
        chapter, section, nearest = _context_at(headings, sum(len(x) + 1 for x in lines[:i]))
        title = nearest or section or ""
        if any(k in title for k in ("经络", "经脉", "胃经", "膀胱经", "任脉", "督脉")) or (
            "经" in title and len(title) <= 12
        ):
            if any(k in line for k in ("组成", "起于", "主治", "联系", "运行气血", "循行")):
                topic = title or "经络"
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or topic,
                        card_type="meridian_overview",
                        question=f"{topic}的要点是什么？",
                        answer=line,
                        source_excerpt=line,
                        tags=[topic, "经络"],
                        chunk_id=f"{chunk_id_prefix}.meridian.{i}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.86,
                        generation_batch_id=generation_batch_id,
                    )
                )

    for t_i, match in enumerate(TABLE_RE.finditer(md)):
        tables = parse_html_tables(match.group(0))
        if not tables:
            continue
        rows = tables[0]
        chapter, section, _ = _context_at(headings, match.start())
        chunk_base = f"{chunk_id_prefix}.t{t_i}"

        # generic caution kv
        if len(rows) <= 4 and any(_clean(r[0]) in {"注意事项", "注意", "禁忌"} for r in rows if r):
            for r_i, row in enumerate(rows):
                if len(row) < 2:
                    continue
                key = _clean(row[0])
                val = _clean(" ".join(row[1:]))
                if key in {"注意事项", "注意", "禁忌"} and val:
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or "针刺注意事项",
                            card_type="acupoint_caution",
                            question="毫针刺法有哪些注意事项？",
                            answer=val,
                            source_excerpt=f"{key}：{val}",
                            tags=["针刺", "注意事项"],
                            chunk_id=f"{chunk_base}.caution.{r_i}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
            continue

        if not _looks_like_acupoint_table(rows):
            continue

        header = [_clean(c) for c in rows[0]]
        col = _header_index_map(
            header,
            {
                "name": ("穴位", "腧穴", "穴名"),
                "location": ("定位",),
                "indication": ("主治",),
                "operation": ("刺灸", "操作", "针法"),
                "special": ("特定穴",),
            },
        )
        if "name" not in col:
            continue
        for r_i, row in enumerate(rows[1:], start=1):
            name = _clean(row[col["name"]]) if col["name"] < len(row) else ""
            if not name or len(name) > 12:
                continue
            loc = (
                _clean(row[col["location"]])
                if "location" in col and col["location"] < len(row)
                else ""
            )
            ind = (
                _clean(row[col["indication"]])
                if "indication" in col and col["indication"] < len(row)
                else ""
            )
            op = (
                _clean(row[col["operation"]])
                if "operation" in col and col["operation"] < len(row)
                else ""
            )
            if loc:
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or name,
                        card_type="acupoint_location",
                        question=f"{name}的定位是什么？",
                        answer=loc,
                        source_excerpt=f"{name} 定位：{loc}",
                        tags=[name, "定位"],
                        chunk_id=f"{chunk_base}.{r_i}.loc",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.92,
                        generation_batch_id=generation_batch_id,
                    )
                )
            if ind:
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or name,
                        card_type="acupoint_indication",
                        question=f"{name}的主治是什么？",
                        answer=ind,
                        source_excerpt=f"{name} 主治：{ind}",
                        tags=[name, "主治"],
                        chunk_id=f"{chunk_base}.{r_i}.ind",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
            if op:
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or name,
                        card_type="acupoint_operation",
                        question=f"{name}的刺灸法/操作是什么？",
                        answer=op,
                        source_excerpt=f"{name} 刺灸法：{op}",
                        tags=[name, "刺灸法"],
                        chunk_id=f"{chunk_base}.{r_i}.op",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.9,
                        generation_batch_id=generation_batch_id,
                    )
                )
                if ACUPOINT_CAUTION_RE.search(op):
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or name,
                            card_type="acupoint_caution",
                            question=f"{name}针刺时有哪些注意/禁忌？",
                            answer=op,
                            source_excerpt=f"{name} 注意：{op}",
                            tags=[name, "注意事项"],
                            chunk_id=f"{chunk_base}.{r_i}.caution",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )

    return _dedupe_cards(cards)


def extract_renwen_cards(
    md: str,
    *,
    document_version: str,
    document_key: str = "renwen",
    book: str = "人文",
    chunk_id_prefix: str = "renwen.fixture",
    generation_batch_id: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Extract renwen template cards from cleaned markdown."""
    headings = _heading_stack(md)
    cards: list[CandidateCardV2] = []
    lines = md.splitlines()

    # ethics principle tables and prose
    for t_i, match in enumerate(TABLE_RE.finditer(md)):
        tables = parse_html_tables(match.group(0))
        if not tables:
            continue
        rows = tables[0]
        chapter, section, _ = _context_at(headings, match.start())
        header = [_clean(c) for c in rows[0]] if rows else []
        header_join = "".join(header)
        # principle map table
        if any(k in header_join for k in ("原则", "说明", "权利", "义务")) or any(
            any(p in _clean(r[0]) for p in ETHICS_PRINCIPLE_KEYS) for r in rows if r
        ):
            data_rows = rows[1:] if any(k in header_join for k in ("原则", "说明")) else rows
            for r_i, row in enumerate(data_rows):
                if len(row) < 2:
                    continue
                key = _clean(row[0])
                val = _clean(" ".join(row[1:]))
                if not key or not val:
                    continue
                if any(p in key for p in ETHICS_PRINCIPLE_KEYS) or key.endswith("原则"):
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or key,
                            card_type="ethics_principle",
                            question=f"{key}的内涵是什么？",
                            answer=val,
                            source_excerpt=f"{key}：{val}",
                            tags=[key, "伦理原则"],
                            chunk_id=f"{chunk_id_prefix}.t{t_i}.principle.{r_i}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )
                elif "知情同意" in key:
                    cards.append(
                        _make_card(
                            book=book,
                            document_key=document_key,
                            document_version=document_version,
                            chapter=chapter,
                            section=section or key,
                            card_type="ethics_principle",
                            question="知情同意原则的内涵是什么？",
                            answer=val,
                            source_excerpt=f"{key}：{val}",
                            tags=["知情同意", "伦理原则"],
                            chunk_id=f"{chunk_id_prefix}.t{t_i}.consent.{r_i}",
                            pdf_page_index=pdf_page_index,
                            printed_page_label=printed_page_label,
                            confidence=0.9,
                            generation_batch_id=generation_batch_id,
                        )
                    )

    for i, raw in enumerate(lines):
        if HEADING_RE.match(raw):
            continue
        line = _clean(raw)
        if not line:
            continue
        chapter, section, nearest = _context_at(headings, sum(len(x) + 1 for x in lines[:i]))

        # regulation with optional date / statute name
        if (
            STATUTE_RE.search(line)
            or ("医师" in line and "义务" in line)
            or DATE_RE.search(line)
            and any(k in line for k in ("施行", "规定", "法律", "条例", "医师"))
        ):
            tags = ["法规"]
            for m in STATUTE_RE.findall(line):
                tags.append(m)
            for m in DATE_RE.findall(line):
                tags.append(_clean(m))
            # ensure document_version retained; also surface date in tags
            cards.append(
                _make_card(
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or nearest,
                    card_type="regulation_fact",
                    question="相关法规的要点是什么？",
                    answer=line,
                    source_excerpt=line,
                    tags=tags,
                    chunk_id=f"{chunk_id_prefix}.reg.{i}",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    confidence=0.88,
                    generation_batch_id=generation_batch_id,
                    status=CandidateStatus.NEEDS_REVIEW,
                    review_notes="法规时效敏感，核对施行日期与条文版本。",
                )
            )
            continue

        # scenario judgment
        if any(k in (nearest or "") for k in ("情境", "场景", "判断")) or (
            any(k in line for k in ("应", "应当", "可", "不宜"))
            and any(k in line for k in ("患者", "知情", "同意", "隐私", "拒绝"))
            and len(line) >= 20
        ):
            if "情境" in (nearest or "") or (
                "患者" in line and any(k in line for k in ("知情", "同意", "拒绝", "隐私"))
            ):
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or nearest,
                        card_type="ethics_scenario",
                        question="该伦理情境下应如何判断与处理？",
                        answer=line,
                        source_excerpt=line,
                        tags=["伦理情境", section or "情境"],
                        chunk_id=f"{chunk_id_prefix}.scenario.{i}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.84,
                        generation_batch_id=generation_batch_id,
                    )
                )
                continue

        # principles prose summary
        if "基本原则" in (section or "") or "基本原则" in (nearest or ""):
            if any(p in line for p in ETHICS_PRINCIPLE_KEYS) and len(line) >= 8:
                cards.append(
                    _make_card(
                        book=book,
                        document_key=document_key,
                        document_version=document_version,
                        chapter=chapter,
                        section=section or nearest,
                        card_type="ethics_principle",
                        question="医学伦理学的基本原则有哪些？",
                        answer=line,
                        source_excerpt=line,
                        tags=["伦理原则", "基本原则"],
                        chunk_id=f"{chunk_id_prefix}.principles.prose.{i}",
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_page_label,
                        confidence=0.86,
                        generation_batch_id=generation_batch_id,
                    )
                )
                continue

        # history / figure facts
        if HISTORY_HINT_RE.search(line) and len(line) >= 12:
            cards.append(
                _make_card(
                    book=book,
                    document_key=document_key,
                    document_version=document_version,
                    chapter=chapter,
                    section=section or nearest,
                    card_type="history_fact",
                    question="相关历史/人物事实是什么？",
                    answer=line,
                    source_excerpt=line,
                    tags=["历史事实"],
                    chunk_id=f"{chunk_id_prefix}.history.{i}",
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_page_label,
                    confidence=0.8,
                    generation_batch_id=generation_batch_id,
                )
            )

    return _dedupe_cards(cards)


def extract_neike_zhenjiu_renwen_cards(
    md: str,
    *,
    book_template: str,
    document_version: str,
    generation_batch_id: str | None = None,
    chunk_id_prefix: str | None = None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Dispatch helper for neike/zhenjiu/renwen book templates."""
    key = book_template.strip().lower()
    if key == "neike":
        return extract_neike_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "neike.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key == "zhenjiu":
        return extract_zhenjiu_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "zhenjiu.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key == "renwen":
        return extract_renwen_cards(
            md,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix or "renwen.fixture",
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    raise ValueError(f"unsupported book_template for P5-T04: {book_template!r}")


__all__ = [
    "GENERATOR",
    "PROMPT_VERSION",
    "extract_neike_cards",
    "extract_neike_zhenjiu_renwen_cards",
    "extract_renwen_cards",
    "extract_zhenjiu_cards",
]
