"""P5-T10: first formal 7-book publication batch."""

from __future__ import annotations

import json
from pathlib import Path

from tools.document_pipeline.candidate_schema import CandidateStatus, RiskLevel
from tools.document_pipeline.first_publication import (
    BOOK_SPECS,
    PUBLICATION_ID,
    STAGE,
    build_first_publication,
    extract_first_batch_candidates,
    review_first_batch,
    write_review_artifacts,
)
from tools.document_pipeline.publish import verify_package_checksums


def test_extract_first_batch_covers_seven_books() -> None:
    cards = extract_first_batch_candidates()
    books = {c.book for c in cards}
    keys = {c.document_key for c in cards}
    assert len(BOOK_SPECS) == 7
    assert books == {spec["book"] for spec in BOOK_SPECS}
    assert keys == {spec["key"] for spec in BOOK_SPECS}
    assert len(cards) >= 68  # golden fixtures currently yield ~71 after intra-fixture dedupe
    # every book has at least one chapter worth of cards
    for spec in BOOK_SPECS:
        book_cards = [c for c in cards if c.document_key == spec["key"]]
        assert book_cards, spec["key"]
        assert any((c.chapter or "").strip() for c in book_cards)


def test_review_approves_all_including_critical() -> None:
    cards = extract_first_batch_candidates()
    bundle = review_first_batch(cards, reviewer="tester")
    assert all(c.status == CandidateStatus.APPROVED for c in bundle.cards.values())
    high = [
        c for c in bundle.cards.values() if c.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    ]
    assert high
    assert all(c.reviewer == "tester" and c.reviewed_at for c in high)
    # each book reviewed at least one chapter (audit contains chapter batch notes)
    books = {c.book for c in bundle.cards.values()}
    notes = " ".join(e.notes or "" for e in bundle.audit)
    for book in books:
        assert book in notes


def test_build_first_publication_package(tmp_path: Path) -> None:
    result = build_first_publication(out_dir=tmp_path / "pub", publication_id=PUBLICATION_ID)
    assert result.publication_id == PUBLICATION_ID
    assert len(result.book_summaries) == 7
    assert result.source_coverage == 1.0
    assert result.high_risk_review_coverage == 1.0
    assert result.package.card_count == len(result.cards)
    assert result.package.card_count >= 68

    out = result.package.out_dir
    for name in [
        "manifest.json",
        "documents.json",
        "chapters.json",
        "chunks.jsonl",
        "cards.jsonl",
        "card_sources.jsonl",
        "checksums.json",
        "quality-summary.json",
    ]:
        assert (out / name).exists(), name

    verify = verify_package_checksums(out)
    assert verify["ok"] is True

    docs = json.loads((out / "documents.json").read_text(encoding="utf-8"))
    assert {d["document_key"] for d in docs} == {spec["key"] for spec in BOOK_SPECS}
    assert all(d.get("subject") for d in docs)

    cards = [
        json.loads(line)
        for line in (out / "cards.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(c["status"] == "approved" for c in cards)
    high = [c for c in cards if c["risk_level"] in {"high", "critical"}]
    assert high
    assert all(c.get("reviewer") and c.get("reviewed_at") for c in high)

    sources = [
        json.loads(line)
        for line in (out / "card_sources.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sourced_ids = {s["card_id"] for s in sources}
    assert sourced_ids == {c["id"] for c in cards}

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publication_id"] == PUBLICATION_ID
    assert manifest["counts"]["cards"] == len(cards)
    assert manifest["counts"]["documents"] == 7

    artifacts = write_review_artifacts(result.review_bundle, tmp_path / "review")
    assert Path(artifacts["review_bundle"]).exists()
    payload = json.loads(Path(artifacts["review_bundle"]).read_text(encoding="utf-8"))
    assert payload["status"] == "candidate_review_only"
    assert payload["card_count"] == len(cards)
    assert STAGE == "first_publication"


def test_first_publication_default_build_is_hash_reproducible(tmp_path: Path) -> None:
    first = build_first_publication(out_dir=tmp_path / "first", publication_id=PUBLICATION_ID)
    second = build_first_publication(out_dir=tmp_path / "second", publication_id=PUBLICATION_ID)

    assert first.package.manifest["package_hash"] == second.package.manifest["package_hash"]
    assert first.package.manifest["manifest_hash"] == second.package.manifest["manifest_hash"]
