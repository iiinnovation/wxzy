"""P5-T06: automated candidate validation and near-duplicate tests."""

from __future__ import annotations

import json
from pathlib import Path

from tools.document_pipeline.candidate_validation import (
    STAGE,
    STAGE_VERSION,
    extract_dosage_claims,
    find_near_duplicates,
    load_candidates,
    validate_candidate_batch,
    validate_card,
)
from tools.document_pipeline.paths import ROOT

FIXTURE = ROOT / "tools" / "document_pipeline" / "fixtures" / "validation_p5t06_cards.json"


def _cards() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cards"]


def test_valid_control_passes() -> None:
    card = _cards()["valid_control"]
    result = validate_card(card)
    assert result.ok, result.issues
    assert result.card_id == card["id"]


def test_fabricated_dosage_is_intercepted() -> None:
    card = _cards()["fabricated_dosage"]
    # sanity: claim extractor sees 九两
    claims = extract_dosage_claims(card["answer"])
    assert any("九两" in c or "9两" in c for c in claims)
    result = validate_card(card)
    assert not result.ok
    codes = {i.code for i in result.issues}
    assert "fabricated_dosage" in codes


def test_no_source_answer_is_intercepted() -> None:
    card = _cards()["no_source_coverage"]
    result = validate_card(card)
    assert not result.ok
    codes = {i.code for i in result.issues}
    assert "source_coverage_fail" in codes


def test_duplicate_questions_are_intercepted() -> None:
    cards = _cards()
    batch = validate_candidate_batch([cards["duplicate_a"], cards["duplicate_b"]])
    assert not batch.ok
    assert batch.rejected_count == 2
    assert batch.accepted_count == 0
    codes = {i.code for r in batch.results for i in r.issues}
    assert "near_duplicate" in codes
    # also direct near-dup map
    from tools.document_pipeline.candidate_schema import CandidateCardV2

    models = [
        CandidateCardV2.model_validate(cards["duplicate_a"]),
        CandidateCardV2.model_validate(cards["duplicate_b"]),
    ]
    near = find_near_duplicates(models)
    assert near[models[0].id]
    assert near[models[1].id]


def test_multi_version_mix_is_intercepted() -> None:
    card = _cards()["multi_version_mix"]
    result = validate_card(card)
    assert not result.ok
    codes = {i.code for i in result.issues}
    assert "multi_version_mix" in codes


def test_single_version_card_passes() -> None:
    card = _cards()["single_version_ok"]
    result = validate_card(card)
    assert result.ok, [i.to_dict() for i in result.issues]


def test_long_answer_without_points_is_intercepted() -> None:
    card = _cards()["long_answer_no_points"]
    result = validate_card(card)
    assert not result.ok
    codes = {i.code for i in result.issues}
    assert "missing_min_knowledge_point" in codes


def test_batch_accepts_only_clean_cards(tmp_path: Path) -> None:
    cards = _cards()
    batch_cards = [
        cards["valid_control"],
        cards["fabricated_dosage"],
        cards["no_source_coverage"],
        cards["duplicate_a"],
        cards["duplicate_b"],
        cards["multi_version_mix"],
        cards["single_version_ok"],
        cards["long_answer_no_points"],
    ]
    batch = validate_candidate_batch(batch_cards)
    assert batch.stage == STAGE
    assert batch.stage_version == STAGE_VERSION
    assert batch.accepted_count == 2
    assert {c.id for c in batch.accepted} == {
        cards["valid_control"]["id"],
        cards["single_version_ok"]["id"],
    }
    assert batch.rejected_count == 6
    batch.write(tmp_path)
    report = json.loads((tmp_path / "validation_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "candidate_only"
    assert report["accepted_count"] == 2
    assert (tmp_path / "accepted.jsonl").exists()
    assert (tmp_path / "rejected.jsonl").exists()


def test_load_candidates_from_fixture_dict() -> None:
    # load_candidates supports list/jsonl/dict-with-cards; here exercise list path
    cards = list(_cards().values())
    loaded = load_candidates(cards)
    assert len(loaded) == len(cards)
