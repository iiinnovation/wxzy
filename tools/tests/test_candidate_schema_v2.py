"""P5-T01: Candidate Card v2 schema, converter, and gate."""

from __future__ import annotations

import json

import pytest
from tools.document_pipeline.candidate_schema import (
    CANDIDATE_CARD_V2_SCHEMA_PATH,
    CANDIDATE_SCHEMA_VERSION,
    CandidateGateError,
    CandidateStatus,
    RiskLevel,
    compute_content_hash,
    convert_v1_card_to_v2,
    convert_v1_payload_to_v2,
    gate_candidate_card,
    load_candidate_card_v2_schema,
    load_v1_sample_cards,
    validate_candidate_card_v2,
)
from tools.document_pipeline.paths import ROOT, SCHEMA_PATH

SEED_V1 = ROOT / "server" / "seed_data" / "candidates_offline_v1.json"


def _with_provenance(card: dict) -> dict:
    excerpt = str(card.get("source_excerpt") or card["question"])
    chunk_id = f"legacy.{card['id']}.chunk0"
    return convert_v1_card_to_v2(
        card,
        chunk_ids=[chunk_id],
        sources=[
            {
                "citation_order": 0,
                "chunk_id": chunk_id,
                "excerpt": excerpt,
                "pdf_page_index_start": 0,
                "pdf_page_index_end": 0,
                "printed_page_start_label": "1",
                "printed_page_end_label": "1",
            }
        ],
        pdf_page_indexes=[0],
        printed_page_labels=["1"],
    ).model_dump(mode="json")


def test_tracked_v2_schema_exists_and_is_versioned() -> None:
    schema = load_candidate_card_v2_schema()
    assert CANDIDATE_CARD_V2_SCHEMA_PATH.is_file()
    assert SCHEMA_PATH == CANDIDATE_CARD_V2_SCHEMA_PATH
    assert schema["$id"].endswith("candidate_card.v2.schema.json")
    assert schema["properties"]["schema_version"]["const"] == CANDIDATE_SCHEMA_VERSION
    required = set(schema["required"])
    for key in (
        "document_version",
        "chunk_ids",
        "pdf_page_indexes",
        "printed_page_labels",
        "risk_level",
        "risk_flags",
        "content_hash",
        "generator",
        "prompt_version",
        "reviewer",
        "reviewed_at",
        "review_notes",
    ):
        assert key in schema["properties"]
    assert "document_version" in required
    assert "risk_level" in required
    assert "content_hash" in required


def test_all_18_offline_v1_samples_convert_to_v2() -> None:
    payload = json.loads(SEED_V1.read_text(encoding="utf-8"))
    assert payload["count"] == 18
    assert len(payload["cards"]) == 18

    converted = convert_v1_payload_to_v2(payload)
    assert converted["schema_version"] == 2
    assert converted["count"] == 18
    assert len(converted["cards"]) == 18

    cards = load_v1_sample_cards()
    assert len(cards) == 18
    for raw, out in zip(cards, converted["cards"], strict=True):
        assert out["schema_version"] == 2
        assert out["id"] == raw["id"]
        assert out["book"] == raw["book"]
        assert out["card_type"] == raw["type"]
        assert out["question"] == raw["question"]
        assert out["answer"] == raw["answer"]
        assert out["document_key"] in {"fangji", "neike"}
        assert out["document_version"]
        assert out["generator"]
        assert out["prompt_version"]
        assert out["content_hash"]
        assert out["risk_level"] in {level.value for level in RiskLevel}
        assert out["status"] in {status.value for status in CandidateStatus}
        # content hash is deterministic
        assert out["content_hash"] == compute_content_hash(
            document_version=out["document_version"],
            card_type=out["card_type"],
            question=out["question"],
            answer=out["answer"],
            answer_points=out["answer_points"],
            source_excerpt=out["source_excerpt"],
            chunk_ids=out["chunk_ids"],
        )


def test_converted_samples_with_provenance_pass_gate() -> None:
    cards = load_v1_sample_cards()
    for raw in cards:
        enriched = _with_provenance(raw)
        model = validate_candidate_card_v2(enriched)
        assert model.chunk_ids
        assert model.sources
        if model.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            assert model.risk_flags


def test_gate_fails_without_source_provenance() -> None:
    raw = load_v1_sample_cards()[0]
    bare = convert_v1_card_to_v2(raw)
    errors = gate_candidate_card(bare)
    assert any("provenance" in err or "source" in err for err in errors)
    with pytest.raises(CandidateGateError) as excinfo:
        validate_candidate_card_v2(bare)
    assert excinfo.value.errors


def test_gate_fails_when_high_risk_missing_flags() -> None:
    raw = load_v1_sample_cards()[0]
    enriched = convert_v1_card_to_v2(
        raw,
        chunk_ids=["chunk-a"],
        sources=[
            {
                "citation_order": 0,
                "chunk_id": "chunk-a",
                "excerpt": raw["source_excerpt"],
                "pdf_page_index_start": 1,
                "pdf_page_index_end": 1,
            }
        ],
        pdf_page_indexes=[1],
        risk_level="high",
        risk_flags=[],
    )
    errors = gate_candidate_card(enriched)
    assert any("risk_flags" in err for err in errors)
    with pytest.raises(CandidateGateError):
        validate_candidate_card_v2(enriched)


def test_gate_fails_when_critical_missing_flags() -> None:
    raw = next(c for c in load_v1_sample_cards() if c["type"] == "versioned_classification")
    enriched = convert_v1_card_to_v2(
        raw,
        chunk_ids=["chunk-v"],
        sources=[
            {
                "citation_order": 0,
                "chunk_id": "chunk-v",
                "excerpt": raw["source_excerpt"],
                "pdf_page_index_start": 2,
                "pdf_page_index_end": 2,
            }
        ],
        pdf_page_indexes=[2],
        risk_level="critical",
        risk_flags=[],
    )
    with pytest.raises(CandidateGateError) as excinfo:
        validate_candidate_card_v2(enriched)
    assert any("risk_flags" in err for err in excinfo.value.errors)


def test_content_hash_changes_when_answer_changes() -> None:
    raw = load_v1_sample_cards()[0]
    first = convert_v1_card_to_v2(raw, chunk_ids=["c1"])
    changed = dict(raw)
    changed["answer"] = raw["answer"] + "（改）"
    second = convert_v1_card_to_v2(changed, chunk_ids=["c1"])
    assert first.content_hash != second.content_hash
