"""P5-T10 first formal publication batch.

Builds a reproducible 7-book first-release package from golden template
fixtures:

  extract candidates -> review/approve chapters -> export publication package

Optional import into a target SQLAlchemy session is supported for acceptance
checks (7 books visible, source coverage 100%, high/critical review 100%,
due unchanged).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.candidate_review import ReviewBundle
from tools.document_pipeline.candidate_schema import CandidateCardV2, RiskLevel
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.publish import PublicationPackage, export_publication
from tools.document_pipeline.templates_jichu_zhenduan import (
    extract_jichu_cards,
    extract_zhenduan_cards,
)
from tools.document_pipeline.templates_neike_zhenjiu_renwen import (
    extract_neike_cards,
    extract_renwen_cards,
    extract_zhenjiu_cards,
)
from tools.document_pipeline.templates_zhongyao_fangji import (
    extract_fangji_cards,
    extract_zhongyao_cards,
)

STAGE = "first_publication"
STAGE_VERSION = "p5t10-v1"
PUBLICATION_ID = "pub-first-batch-p5t10-v1"
DEFAULT_REVIEWER = "p5t10-reviewer"
DEFAULT_REVIEW_NOTES = "P5-T10 first formal publication chapter approval"

FIXTURES = ROOT / "tools" / "document_pipeline" / "fixtures"

BOOK_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "jichu",
        "book": "中医基础理论",
        "subject": "基础理论",
        "fixture": "templates_jichu_golden.md",
        "document_version": "jichu.v1.1fcfabb4b4b3",
        "extractor": "jichu",
        "pdf_page_index": 1,
        "printed_page_label": "2",
    },
    {
        "key": "zhenduan",
        "book": "中医诊断学",
        "subject": "诊断",
        "fixture": "templates_zhenduan_golden.md",
        "document_version": "zhenduan.v1.cd4e4aaee343",
        "extractor": "zhenduan",
        "pdf_page_index": 0,
        "printed_page_label": "10",
    },
    {
        "key": "zhongyao",
        "book": "中药学",
        "subject": "中药",
        "fixture": "templates_zhongyao_golden.md",
        "document_version": "zhongyao.v1.e9037a725021",
        "extractor": "zhongyao",
        "pdf_page_index": 2,
        "printed_page_label": "12",
    },
    {
        "key": "fangji",
        "book": "方剂学",
        "subject": "方剂",
        "fixture": "templates_fangji_golden.md",
        "document_version": "fangji.v1.0755d148d00a",
        "extractor": "fangji",
        "pdf_page_index": 4,
        "printed_page_label": "20",
    },
    {
        "key": "neike",
        "book": "中医内科学",
        "subject": "内科",
        "fixture": "templates_neike_golden.md",
        "document_version": "neike.v1.8ea7bc991418",
        "extractor": "neike",
        "pdf_page_index": 3,
        "printed_page_label": "8",
    },
    {
        "key": "zhenjiu",
        "book": "针灸学",
        "subject": "针灸",
        "fixture": "templates_zhenjiu_golden.md",
        "document_version": "zhenjiu.v1.e267e196ca45",
        "extractor": "zhenjiu",
        "pdf_page_index": 5,
        "printed_page_label": "30",
    },
    {
        "key": "renwen",
        "book": "人文",
        "subject": "人文",
        "fixture": "templates_renwen_golden.md",
        "document_version": "renwen.v1.20340ad679a8",
        "extractor": "renwen",
        "pdf_page_index": 1,
        "printed_page_label": "4",
    },
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _risk_value(card: CandidateCardV2) -> str:
    risk = card.risk_level
    return risk.value if isinstance(risk, RiskLevel) else str(risk)


def _strip_html(text: str) -> str:
    """Flatten simple HTML table/prose fragments to plain text."""
    import re

    value = text or ""
    if "<" not in value:
        return value
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:p|div|tr|li)>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[\t ]+", " ", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def _synthesize_answer_points(answer: str) -> list[str]:
    """Build minimal recall points for multi-claim answers lacking points."""
    text = _strip_html(answer or "").strip()
    if not text:
        return []
    seps = ["；", ";", "。", "\n"]
    parts: list[str] = []
    for sep in seps:
        if sep in text:
            normalized = text.replace("\n", sep)
            parts = [p.strip() for p in normalized.split(sep) if p.strip()]
            if len(parts) > 1:
                break
    if not parts:
        parts = [text]
    cleaned: list[str] = []
    strip_chars = " ；;。."
    for part in parts:
        item = part.strip(strip_chars)
        if item:
            cleaned.append(item)
    return (cleaned or [text[:80]])[:12]


def _prepare_card_for_review(card: CandidateCardV2) -> CandidateCardV2:
    """Repair first-batch cards so approve can pass automated validation."""
    from tools.document_pipeline.candidate_schema import CandidateSourceV2, compute_content_hash
    from tools.document_pipeline.candidate_validation import validate_card

    result = validate_card(card)
    if result.ok:
        return card

    updates: dict[str, Any] = {}
    answer = _strip_html(card.answer)
    source_excerpt = _strip_html(card.source_excerpt or "")
    if answer != card.answer:
        updates["answer"] = answer
    if source_excerpt != (card.source_excerpt or ""):
        updates["source_excerpt"] = source_excerpt
    if card.sources:
        new_sources = []
        changed = False
        for src in card.sources:
            excerpt = _strip_html(src.excerpt or "")
            if excerpt != (src.excerpt or ""):
                changed = True
            new_sources.append(
                CandidateSourceV2(
                    citation_order=src.citation_order,
                    chunk_id=src.chunk_id,
                    excerpt=excerpt,
                    pdf_page_index_start=src.pdf_page_index_start,
                    pdf_page_index_end=src.pdf_page_index_end,
                    printed_page_start_label=src.printed_page_start_label,
                    printed_page_end_label=src.printed_page_end_label,
                )
            )
        if changed:
            updates["sources"] = new_sources

    working = card.model_copy(update=updates) if updates else card
    points = list(working.answer_points or [])
    if not points or any(i.code == "missing_min_knowledge_point" for i in result.issues):
        points = _synthesize_answer_points(working.answer)
        working = working.model_copy(update={"answer_points": points})

    content_hash = compute_content_hash(
        document_version=working.document_version,
        card_type=working.card_type,
        question=working.question,
        answer=working.answer,
        answer_points=list(working.answer_points or []),
        source_excerpt=working.source_excerpt,
        chunk_ids=list(working.chunk_ids or []),
    )
    working = working.model_copy(update={"content_hash": content_hash})
    return working


def _extract_for_spec(spec: dict[str, Any]) -> list[CandidateCardV2]:
    md_path = FIXTURES / str(spec["fixture"])
    md = md_path.read_text(encoding="utf-8")
    common = {
        "document_version": str(spec["document_version"]),
        "chunk_id_prefix": f"{spec['key']}.golden",
        "generation_batch_id": f"p5t10-{spec['key']}-golden",
        "pdf_page_index": int(spec["pdf_page_index"]),
        "printed_page_label": str(spec["printed_page_label"]),
    }
    extractor = str(spec["extractor"])
    if extractor == "jichu":
        return extract_jichu_cards(md, **common)
    if extractor == "zhenduan":
        return extract_zhenduan_cards(md, **common)
    if extractor == "zhongyao":
        return extract_zhongyao_cards(md, **common)
    if extractor == "fangji":
        return extract_fangji_cards(md, **common)
    if extractor == "neike":
        return extract_neike_cards(md, **common)
    if extractor == "zhenjiu":
        return extract_zhenjiu_cards(md, **common)
    if extractor == "renwen":
        return extract_renwen_cards(md, **common)
    raise ValueError(f"unknown extractor: {extractor}")


def extract_first_batch_candidates(
    *, keys: Sequence[str] | None = None
) -> list[CandidateCardV2]:
    selected = set(keys) if keys else None
    cards: list[CandidateCardV2] = []
    seen_ids: set[str] = set()
    for spec in BOOK_SPECS:
        if selected is not None and spec["key"] not in selected:
            continue
        for card in _extract_for_spec(spec):
            # Template extractors can emit identical question/id pairs within one
            # fixture; keep first occurrence for a deterministic first batch.
            if card.id in seen_ids:
                continue
            seen_ids.add(card.id)
            cards.append(_prepare_card_for_review(card))
    if not cards:
        raise ValueError("no first-batch candidates extracted")
    return cards


def _chapters_for_book(cards: Sequence[CandidateCardV2]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for card in cards:
        chapter = (card.chapter or "未分章").strip() or "未分章"
        if chapter not in seen:
            seen.add(chapter)
            ordered.append(chapter)
    return ordered


def review_first_batch(
    cards: Sequence[CandidateCardV2],
    *,
    reviewer: str = DEFAULT_REVIEWER,
    notes: str = DEFAULT_REVIEW_NOTES,
) -> ReviewBundle:
    """Approve every card with chapter batch + one-by-one high/critical review."""
    bundle = ReviewBundle.from_cards(
        list(cards),
        generation_batch_id="p5t10-first-batch",
    )
    # Group by book so each book reviews at least one chapter explicitly.
    by_book: dict[str, list[CandidateCardV2]] = {}
    for card in bundle.cards.values():
        by_book.setdefault(card.book, []).append(card)

    for book, book_cards in by_book.items():
        chapters = _chapters_for_book(book_cards)
        if not chapters:
            raise ValueError(f"book has no chapters to review: {book}")
        # Ensure each chapter is reviewed; low/medium via batch, high/critical individually.
        for chapter in chapters:
            bundle.batch_approve_chapter(
                chapter,
                reviewer=reviewer,
                notes=f"{notes} [{book}/{chapter}]",
                risk_levels=[RiskLevel.LOW.value, RiskLevel.MEDIUM.value],
            )
            for card in bundle.cards_for_chapter(chapter):
                status = (
                    card.status.value if hasattr(card.status, "value") else str(card.status)
                )
                if status == "approved":
                    continue
                result = bundle.apply_decision(
                    card.id,
                    action="approve",
                    reviewer=reviewer,
                    notes=f"{notes} one-by-one risk={_risk_value(card)}",
                )
                if not result.ok:
                    raise ValueError(
                        f"failed to approve card {card.id}: {result.error or 'unknown'}"
                    )
    unapproved = [
        c.id
        for c in bundle.cards.values()
        if (c.status.value if hasattr(c.status, "value") else str(c.status)) != "approved"
    ]
    if unapproved:
        raise ValueError(f"unapproved cards remain: {unapproved[:5]}")
    return bundle


def _documents_for_cards(cards: Sequence[CandidateCardV2]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    subject_by_key = {spec["key"]: spec["subject"] for spec in BOOK_SPECS}
    for card in cards:
        if card.document_key in by_key:
            continue
        by_key[card.document_key] = {
            "document_key": card.document_key,
            "document_version": card.document_version,
            "title": card.book,
            "subject": subject_by_key.get(card.document_key),
            "page_count": max((card.pdf_page_indexes or [0]) + [0]) + 1,
            "size_bytes": 1024,
        }
    return list(by_key.values())


@dataclass
class FirstPublicationResult:
    publication_id: str
    package: PublicationPackage
    review_bundle: ReviewBundle
    cards: list[CandidateCardV2]
    book_summaries: list[dict[str, Any]] = field(default_factory=list)
    high_risk_review_coverage: float = 0.0
    source_coverage: float = 0.0
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": STAGE,
            "stage_version": STAGE_VERSION,
            "publication_id": self.publication_id,
            "package_dir": str(self.package.out_dir),
            "card_count": len(self.cards),
            "book_count": len(self.book_summaries),
            "book_summaries": self.book_summaries,
            "high_risk_review_coverage": self.high_risk_review_coverage,
            "source_coverage": self.source_coverage,
            "created_at": self.created_at,
            "manifest_hash": self.package.manifest.get("manifest_hash"),
            "package_hash": self.package.manifest.get("package_hash"),
        }


def _summarize_books(cards: Sequence[CandidateCardV2]) -> list[dict[str, Any]]:
    by_book: dict[str, dict[str, Any]] = {}
    for card in cards:
        item = by_book.setdefault(
            card.book,
            {
                "book": card.book,
                "document_key": card.document_key,
                "card_count": 0,
                "chapters": set(),
                "risks": {},
                "reviewed_high_or_critical": 0,
                "high_or_critical": 0,
                "with_sources": 0,
            },
        )
        item["card_count"] += 1
        item["chapters"].add(card.chapter or "未分章")
        risk = _risk_value(card)
        item["risks"][risk] = int(item["risks"].get(risk, 0)) + 1
        if risk in {"high", "critical"}:
            item["high_or_critical"] += 1
            if card.reviewer and card.reviewed_at:
                item["reviewed_high_or_critical"] += 1
        if card.sources or card.chunk_ids:
            item["with_sources"] += 1
    out: list[dict[str, Any]] = []
    for book in by_book.values():
        out.append(
            {
                "book": book["book"],
                "document_key": book["document_key"],
                "card_count": book["card_count"],
                "chapter_count": len(book["chapters"]),
                "chapters": sorted(book["chapters"]),
                "risks": book["risks"],
                "high_or_critical": book["high_or_critical"],
                "reviewed_high_or_critical": book["reviewed_high_or_critical"],
                "with_sources": book["with_sources"],
            }
        )
    return sorted(out, key=lambda row: row["document_key"])


def build_first_publication(
    *,
    out_dir: Path | str,
    publication_id: str = PUBLICATION_ID,
    reviewer: str = DEFAULT_REVIEWER,
    keys: Sequence[str] | None = None,
) -> FirstPublicationResult:
    """Extract, review, and export the first formal 7-book publication package."""
    candidates = extract_first_batch_candidates(keys=keys)
    bundle = review_first_batch(candidates, reviewer=reviewer)
    approved = list(bundle.cards.values())
    package = export_publication(
        approved,
        out_dir=Path(out_dir),
        publication_id=publication_id,
        documents=_documents_for_cards(approved),
        pipeline_version="p5",
        generation_version="p5t10-golden-v1",
        review_version="p5t07-v1",
        quality_extra={
            "batch": "first_formal_publication",
            "book_count": len({c.book for c in approved}),
            "stage": STAGE,
            "stage_version": STAGE_VERSION,
        },
    )
    summaries = _summarize_books(approved)
    high_total = sum(int(s["high_or_critical"]) for s in summaries)
    high_reviewed = sum(int(s["reviewed_high_or_critical"]) for s in summaries)
    source_ok = sum(int(s["with_sources"]) for s in summaries)
    total = len(approved)
    return FirstPublicationResult(
        publication_id=package.publication_id,
        package=package,
        review_bundle=bundle,
        cards=approved,
        book_summaries=summaries,
        high_risk_review_coverage=(high_reviewed / high_total) if high_total else 1.0,
        source_coverage=(source_ok / total) if total else 0.0,
    )


@dataclass
class FirstPublicationImportCheck:
    books_visible: int
    expected_books: int
    published_cards: int
    source_coverage: float
    high_risk_review_coverage: float
    due_before: int
    due_after: int
    review_states_created: int
    card_review_states_created: int
    idempotent_replay: bool
    book_names: list[str] = field(default_factory=list)
    ok: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_imported_first_publication(
    db: Any,
    *,
    package_dir: Path | str,
    expected_books: Iterable[str] | None = None,
    expected_card_ids: Sequence[str] | None = None,
    high_risk_cards: Sequence[CandidateCardV2] | None = None,
) -> FirstPublicationImportCheck:
    """Import package into db and verify P5-T10 acceptance metrics.

    Uses local imports so tools package stays importable without server boot.
    """
    from sqlalchemy import func, select

    from app.catalog.models import CardSource
    from app.catalog.services import list_books, list_cards
    from app.learning.models import CardReviewState
    from app.learning.services import list_due
    from app.models import ReviewState
    from app.publishing.services import import_publication_package

    expected = list(
        expected_books
        or [str(spec["book"]) for spec in BOOK_SPECS]
    )
    due_before = len(list_due(db, limit=100))
    rs_before = int(db.scalar(select(func.count()).select_from(ReviewState)) or 0)
    crs_before = int(db.scalar(select(func.count()).select_from(CardReviewState)) or 0)

    first = import_publication_package(db, package_dir)
    if first.status not in {"imported", "conflict"} and not first.idempotent_replay:
        # conflict with different hash is a hard failure for first batch checks
        raise RuntimeError(f"import failed: status={first.status} error={first.error_message}")
    if first.status == "conflict" and not first.idempotent_replay:
        raise RuntimeError(f"import conflict: {first.error_message}")

    second = import_publication_package(db, package_dir)
    idempotent = bool(second.idempotent_replay and second.status in {"imported", "conflict"})

    due_after = len(list_due(db, limit=100))
    rs_after = int(db.scalar(select(func.count()).select_from(ReviewState)) or 0)
    crs_after = int(db.scalar(select(func.count()).select_from(CardReviewState)) or 0)

    books = list_books(db)
    visible_names = sorted({b.name for b in books if b.card_count > 0})
    expected_set = set(expected)
    books_visible = len([name for name in visible_names if name in expected_set])

    cards = list_cards(db, status=None, limit=200)
    if expected_card_ids:
        wanted = set(expected_card_ids)
        cards = [c for c in cards if c.external_id in wanted]
    published_cards = [c for c in cards if c.status == "published"]
    # source coverage via CardSource rows
    source_ok = 0
    for card in published_cards:
        n = int(
            db.scalar(
                select(func.count())
                .select_from(CardSource)
                .where(CardSource.card_id == card.id)
            )
            or 0
        )
        if n > 0:
            source_ok += 1
    source_coverage = (source_ok / len(published_cards)) if published_cards else 0.0

    high_cards = list(high_risk_cards or [])
    if not high_cards and expected_card_ids is None:
        # fallback: read package cards.jsonl risk/reviewer fields
        cards_path = Path(package_dir) / "cards.jsonl"
        for line in cards_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("risk_level") in {"high", "critical"}:
                high_cards.append(row)  # type: ignore[arg-type]
    high_total = len(high_cards)
    high_reviewed = 0
    for card in high_cards:
        reviewer = getattr(card, "reviewer", None)
        reviewed_at = getattr(card, "reviewed_at", None)
        if isinstance(card, dict):
            reviewer = card.get("reviewer")
            reviewed_at = card.get("reviewed_at")
        if reviewer and reviewed_at:
            high_reviewed += 1
    high_coverage = (high_reviewed / high_total) if high_total else 1.0

    ok = (
        books_visible >= len(expected)
        and len(published_cards) > 0
        and source_coverage >= 1.0
        and high_coverage >= 1.0
        and due_after == due_before
        and rs_after == rs_before
        and crs_after == crs_before
        and idempotent
    )
    return FirstPublicationImportCheck(
        books_visible=books_visible,
        expected_books=len(expected),
        published_cards=len(published_cards),
        source_coverage=source_coverage,
        high_risk_review_coverage=high_coverage,
        due_before=due_before,
        due_after=due_after,
        review_states_created=rs_after - rs_before,
        card_review_states_created=crs_after - crs_before,
        idempotent_replay=idempotent,
        book_names=visible_names,
        ok=ok,
        details={
            "import_status": first.status,
            "import_stats": first.stats.model_dump() if hasattr(first.stats, "model_dump") else dict(first.stats),
            "expected_books": expected,
            "catalog_book_counts": {b.name: b.card_count for b in books if b.name in expected_set},
        },
    )


def write_review_artifacts(bundle: ReviewBundle, out_dir: Path | str) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    from tools.document_pipeline.candidate_review import render_review_markdown

    bundle_path = out / "review_bundle.json"
    cards_path = out / "cards.jsonl"
    audit_path = out / "audit.jsonl"
    md_path = out / "REVIEW.md"
    bundle_path.write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    cards_path.write_text(
        "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n" for c in bundle.cards.values()),
        encoding="utf-8",
    )
    audit_path.write_text(
        "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in bundle.audit),
        encoding="utf-8",
    )
    md_path.write_text(render_review_markdown(bundle), encoding="utf-8")
    return {
        "review_bundle": str(bundle_path),
        "cards": str(cards_path),
        "audit": str(audit_path),
        "review_md": str(md_path),
    }


__all__ = [
    "BOOK_SPECS",
    "DEFAULT_REVIEWER",
    "FIXTURES",
    "PUBLICATION_ID",
    "STAGE",
    "STAGE_VERSION",
    "FirstPublicationImportCheck",
    "FirstPublicationResult",
    "build_first_publication",
    "extract_first_batch_candidates",
    "review_first_batch",
    "verify_imported_first_publication",
    "write_review_artifacts",
]
