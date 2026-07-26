"""P5-T07: human review workflow tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from tools.document_pipeline.candidate_review import ReviewBundle, load_review_bundle
from tools.document_pipeline.candidate_schema import compute_content_hash
from tools.document_pipeline.paths import ROOT

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


def test_approve_reject_second_review_audit_complete(tmp_path: Path) -> None:
    cards = _cards()
    bundle = ReviewBundle.from_cards(
        [cards["valid_control"], cards["single_version_ok"], cards["long_answer_no_points"]],
        document_version="fangji.v1.0755d148d00a",
    )
    ok_id = cards["valid_control"]["id"]
    single_id = cards["single_version_ok"]["id"]
    long_id = cards["long_answer_no_points"]["id"]

    a = bundle.apply_decision(ok_id, action="approve", reviewer="alice", notes="looks good")
    assert a.ok
    assert bundle.get(ok_id).status.value == "approved"
    approved_decision = bundle.get(ok_id).review_decision
    assert approved_decision is not None and approved_decision.value == "approve"

    r = bundle.apply_decision(long_id, action="reject", reviewer="alice", notes="too broad")
    assert r.ok
    assert bundle.get(long_id).status.value == "rejected"

    s = bundle.apply_decision(single_id, action="second_review", reviewer="bob", notes="need PDF")
    assert s.ok
    assert bundle.get(single_id).status.value == "needs_review"
    second_decision = bundle.get(single_id).review_decision
    assert second_decision is not None and second_decision.value == "second_review"

    actions = {e.action for e in bundle.audit}
    assert {"approve", "reject", "second_review"} <= actions
    assert all(e.reviewer for e in bundle.audit)
    assert all(e.at for e in bundle.audit)

    bundle.write(tmp_path)
    assert (tmp_path / "review_bundle.json").exists()
    assert (tmp_path / "audit.jsonl").exists()
    assert (tmp_path / "REVIEW.md").exists()
    reloaded = load_review_bundle(tmp_path / "review_bundle.json")
    assert len(reloaded.audit) == len(bundle.audit)
    assert reloaded.get(ok_id).status.value == "approved"


def test_edit_revalidates_and_blocks_bad_edit() -> None:
    cards = _cards()
    good = cards["valid_control"]
    bundle = ReviewBundle.from_cards([good])

    # good edit: still covered by source
    ok = bundle.apply_decision(
        good["id"],
        action="edit",
        reviewer="carol",
        notes="tighten wording",
        edits={"answer": "清热生津", "answer_points": ["清热生津"]},
    )
    assert ok.ok, ok.error
    edit_decision = bundle.get(good["id"]).review_decision
    assert edit_decision is not None and edit_decision.value == "edit"
    assert bundle.get(good["id"]).status.value == "needs_review"
    assert ok.validation is not None and ok.validation.ok

    # bad edit: fabricated dosage not in source
    bad = bundle.apply_decision(
        good["id"],
        action="edit",
        reviewer="carol",
        notes="bad dose",
        edits={
            "answer": "清热生津，石膏五十两",
            "answer_points": ["清热生津", "石膏五十两"],
        },
    )
    assert not bad.ok
    assert bad.error and "validation" in bad.error
    # card remains previous good edited state
    assert "五十两" not in bundle.get(good["id"]).answer
    assert any(e.action == "edit" and e.error for e in bundle.audit)


def test_critical_cards_cannot_batch_approve() -> None:
    cards = _cards()
    # single_version_ok is critical multi_version classification
    critical = cards["single_version_ok"]
    low = cards["valid_control"]
    assert critical["risk_level"] == "critical"
    assert low["risk_level"] == "medium"

    # put both under same chapter for batch
    low2 = _with_hash({**low, "id": "low-chapter-control", "chapter": "中风"})
    crit2 = _with_hash({**critical, "chapter": "中风"})
    bundle = ReviewBundle.from_cards([low2, crit2])
    results = bundle.batch_approve_chapter("中风", reviewer="dana", notes="chapter batch")
    assert len(results) == 2
    by_id = {r.audit.card_id: r for r in results}
    assert by_id[crit2["id"]].ok is False
    assert (
        "critical" in (by_id[crit2["id"]].error or "").lower()
        or "batch" in (by_id[crit2["id"]].error or "").lower()
    )
    # medium may be skipped by default batch risk filter (low+medium allowed)
    # low2 is medium => should approve
    assert by_id[low2["id"]].ok is True
    assert bundle.get(low2["id"]).status.value == "approved"
    assert bundle.get(crit2["id"]).status.value != "approved"
    assert any(e.action == "batch_skip" for e in bundle.audit)


def test_approve_blocked_when_validation_fails() -> None:
    cards = _cards()
    bad = cards["fabricated_dosage"]
    bundle = ReviewBundle.from_cards([bad])
    result = bundle.apply_decision(bad["id"], action="approve", reviewer="erin")
    assert not result.ok
    assert bundle.get(bad["id"]).status.value != "approved"
    assert any(e.action == "approve" and e.error for e in bundle.audit)
