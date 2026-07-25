"""P5-T08: publication exporter tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tools.document_pipeline.candidate_schema import compute_content_hash
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.publish import (
    PublicationExportError,
    export_publication,
    recompute_checksums,
    verify_package_checksums,
)

FIXTURE = ROOT / "tools" / "document_pipeline" / "fixtures" / "validation_p5t06_cards.json"


def _cards() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cards"]


def _with_hash(card: dict) -> dict:
    out = deepcopy(card)
    out["content_hash"] = compute_content_hash(
        document_version=out["document_version"],
        card_type=out["card_type"],
        question=out["question"],
        answer=out["answer"],
        answer_points=list(out.get("answer_points") or []),
        source_excerpt=out["source_excerpt"],
        chunk_ids=list(out.get("chunk_ids") or []),
    )
    return out


def _approved(card: dict, *, reviewer: str = "alice") -> dict:
    out = _with_hash(card)
    out["status"] = "approved"
    out["reviewer"] = reviewer
    out["reviewed_at"] = "2026-07-25T04:00:00+00:00"
    out["review_decision"] = "approve"
    return out


def test_export_package_layout_and_recomputable_hashes(tmp_path: Path) -> None:
    cards = _cards()
    approved = [
        _approved(cards["valid_control"]),
        _approved(cards["single_version_ok"]),
    ]
    pkg = export_publication(
        approved,
        out_dir=tmp_path / "pub",
        publication_id="pub-test-001",
    )
    out = pkg.out_dir
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

    # hashes recomputable
    actual = recompute_checksums(out)
    recorded = json.loads((out / "checksums.json").read_text(encoding="utf-8"))
    assert actual == recorded["files"]
    verify = verify_package_checksums(out)
    assert verify["ok"] is True

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publication_id"] == "pub-test-001"
    assert manifest["counts"]["cards"] == 2
    assert manifest["package_hash"] == recorded["package_hash"]
    assert "manifest_hash" in manifest

    # no absolute paths / secrets in package JSON files
    blob = "\n".join(
        p.read_text(encoding="utf-8")
        for p in out.iterdir()
        if p.suffix in {".json", ".jsonl"}
    )
    assert "/Users/" not in blob
    assert "api_key" not in blob.lower()
    assert "openid" not in blob.lower()


def test_unreviewed_card_cannot_export(tmp_path: Path) -> None:
    cards = _cards()
    generated = _with_hash(cards["valid_control"])
    generated["status"] = "generated"
    with pytest.raises(PublicationExportError) as exc:
        export_publication([generated], out_dir=tmp_path / "bad1")
    assert any("not approved" in e for e in exc.value.errors)


def test_missing_citation_cannot_export(tmp_path: Path) -> None:
    cards = _cards()
    card = _approved(cards["valid_control"])
    card["sources"] = []
    card["chunk_ids"] = []
    card = _with_hash(card)
    # status still approved but provenance stripped; gate/schema may also fail
    with pytest.raises(PublicationExportError) as exc:
        export_publication([card], out_dir=tmp_path / "bad2")
    joined = " | ".join(exc.value.errors)
    assert "missing source" in joined or "provenance" in joined or "schema/gate" in joined


def test_critical_requires_reviewer(tmp_path: Path) -> None:
    cards = _cards()
    card = _approved(cards["single_version_ok"])
    card["reviewer"] = None
    card["reviewed_at"] = None
    card = _with_hash(card)
    with pytest.raises(PublicationExportError) as exc:
        export_publication([card], out_dir=tmp_path / "bad3")
    assert any("critical" in e and "reviewer" in e for e in exc.value.errors)
