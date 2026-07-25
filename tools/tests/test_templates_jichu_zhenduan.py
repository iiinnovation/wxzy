"""P5-T02: jichu / zhenduan template golden tests."""

from __future__ import annotations

import pytest
from tools.document_pipeline.candidate_schema import (
    CARD_TYPE_DEFAULT_RISK,
    RiskLevel,
    validate_candidate_card_v2,
)
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.templates_jichu_zhenduan import (
    GENERATOR,
    PROMPT_VERSION,
    extract_jichu_cards,
    extract_jichu_zhenduan_cards,
    extract_zhenduan_cards,
)

FIXTURES = ROOT / "tools" / "document_pipeline" / "fixtures"
JICHU_MD = FIXTURES / "templates_jichu_golden.md"
ZHENDUAN_MD = FIXTURES / "templates_zhenduan_golden.md"
STRUCTURE_JICHU = FIXTURES / "structure_jichu.md"
STRUCTURE_ZHENDUAN = FIXTURES / "structure_zhenduan.md"

JICHU_VERSION = "jichu.v1.1fcfabb4b4b3"
ZHENDUAN_VERSION = "zhenduan.v1.cd4e4aaee343"


@pytest.fixture(scope="module")
def jichu_cards():
    md = JICHU_MD.read_text(encoding="utf-8")
    return extract_jichu_cards(
        md,
        document_version=JICHU_VERSION,
        chunk_id_prefix="jichu.golden",
        generation_batch_id="p5t02-jichu-golden",
        pdf_page_index=1,
        printed_page_label="2",
    )


@pytest.fixture(scope="module")
def zhenduan_cards():
    md = ZHENDUAN_MD.read_text(encoding="utf-8")
    return extract_zhenduan_cards(
        md,
        document_version=ZHENDUAN_VERSION,
        chunk_id_prefix="zhenduan.golden",
        generation_batch_id="p5t02-zhenduan-golden",
        pdf_page_index=0,
        printed_page_label="10",
    )


def test_jichu_risk_types_registered() -> None:
    for ctype in ("concept_definition", "mechanism", "relation", "contrast"):
        assert ctype in CARD_TYPE_DEFAULT_RISK


def test_zhenduan_risk_types_registered() -> None:
    for ctype in ("four_exam", "symptom_syndrome", "syndrome", "differential"):
        assert ctype in CARD_TYPE_DEFAULT_RISK


def test_jichu_golden_covers_required_templates(jichu_cards) -> None:
    types = {c.card_type for c in jichu_cards}
    assert {
        "concept_definition",
        "mechanism",
        "relation",
        "contrast",
    }.issubset(types)
    assert len(jichu_cards) >= 6


def test_jichu_concept_definition_content(jichu_cards) -> None:
    concepts = [c for c in jichu_cards if c.card_type == "concept_definition"]
    assert concepts
    hit = next(c for c in concepts if "阴阳" in c.question)
    assert "对立双方" in hit.answer or "相互关联" in hit.answer
    assert hit.document_key == "jichu"
    assert hit.document_version == JICHU_VERSION
    assert hit.risk_level == RiskLevel.LOW
    assert hit.risk_flags == []
    assert hit.generator == GENERATOR
    assert hit.prompt_version == PROMPT_VERSION


def test_jichu_relation_and_mechanism(jichu_cards) -> None:
    relations = [c for c in jichu_cards if c.card_type == "relation"]
    mechanisms = [c for c in jichu_cards if c.card_type == "mechanism"]
    assert any("气能生精" in c.question or "气能生精" in c.source_excerpt for c in relations)
    assert any("病理" in c.question or "病理" in c.source_excerpt for c in mechanisms)
    assert all(c.risk_level == RiskLevel.MEDIUM for c in relations + mechanisms)


def test_jichu_contrast(jichu_cards) -> None:
    contrasts = [c for c in jichu_cards if c.card_type == "contrast"]
    assert contrasts
    assert any("阴" in c.answer and "阳" in c.answer for c in contrasts)
    assert all(c.risk_level == RiskLevel.MEDIUM for c in contrasts)


def test_zhenduan_golden_covers_required_templates(zhenduan_cards) -> None:
    types = {c.card_type for c in zhenduan_cards}
    assert {
        "four_exam",
        "symptom_syndrome",
        "syndrome",
        "differential",
    }.issubset(types)
    assert len(zhenduan_cards) >= 8


def test_zhenduan_four_exam(zhenduan_cards) -> None:
    exams = [c for c in zhenduan_cards if c.card_type == "four_exam"]
    names = {c.question for c in exams}
    for label in ("望诊", "闻诊", "问诊", "切诊"):
        assert any(label in q for q in names)
    assert all(c.risk_level == RiskLevel.LOW for c in exams)


def test_zhenduan_syndrome_and_differential(zhenduan_cards) -> None:
    syndromes = [c for c in zhenduan_cards if c.card_type == "syndrome"]
    diffs = [c for c in zhenduan_cards if c.card_type == "differential"]
    assert any("气虚证" in c.question for c in syndromes)
    assert any("辨证要点" in c.question for c in syndromes)
    assert any("气虚证与血虚证" in c.question or "鉴别" in c.question for c in diffs)
    assert all(c.risk_level == RiskLevel.HIGH for c in syndromes + diffs)
    assert all(c.risk_flags for c in syndromes + diffs)


def test_zhenduan_symptom_syndrome_mapping(zhenduan_cards) -> None:
    maps = [c for c in zhenduan_cards if c.card_type == "symptom_syndrome"]
    assert any("淡白舌" in c.question and "气血两虚" in c.answer for c in maps)
    assert all(c.risk_level == RiskLevel.MEDIUM for c in maps)


def test_all_golden_cards_pass_v2_gate(jichu_cards, zhenduan_cards) -> None:
    for card in [*jichu_cards, *zhenduan_cards]:
        model = validate_candidate_card_v2(card)
        assert model.chunk_ids
        assert model.sources
        assert model.pdf_page_indexes
        assert model.content_hash


def test_structure_fixtures_also_extract_basic_cards() -> None:
    jichu = extract_jichu_zhenduan_cards(
        STRUCTURE_JICHU.read_text(encoding="utf-8"),
        book_template="jichu",
        document_version="jichu.fixture.v1",
    )
    zhenduan = extract_jichu_zhenduan_cards(
        STRUCTURE_ZHENDUAN.read_text(encoding="utf-8"),
        book_template="zhenduan",
        document_version="zhenduan.fixture.v1",
    )
    assert any(c.card_type == "concept_definition" for c in jichu)
    assert any(c.card_type in {"relation", "contrast"} for c in jichu)
    assert any(c.card_type == "symptom_syndrome" for c in zhenduan)


def test_dispatch_rejects_unknown_template() -> None:
    with pytest.raises(ValueError):
        extract_jichu_zhenduan_cards(
            "# x\n",
            book_template="fangji",
            document_version="fangji.v1.x",
        )
