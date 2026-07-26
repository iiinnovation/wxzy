"""P5-T04: neike / zhenjiu / renwen template golden tests."""

from __future__ import annotations

import pytest
from tools.document_pipeline.candidate_schema import (
    CARD_TYPE_DEFAULT_RISK,
    RiskLevel,
    validate_candidate_card_v2,
)
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.templates_neike_zhenjiu_renwen import (
    GENERATOR,
    PROMPT_VERSION,
    extract_neike_cards,
    extract_neike_zhenjiu_renwen_cards,
    extract_renwen_cards,
    extract_zhenjiu_cards,
)

FIXTURES = ROOT / "tools" / "document_pipeline" / "fixtures"
NEIKE_MD = FIXTURES / "templates_neike_golden.md"
ZHENJIU_MD = FIXTURES / "templates_zhenjiu_golden.md"
RENWEN_MD = FIXTURES / "templates_renwen_golden.md"
STRUCTURE_NEIKE = FIXTURES / "structure_neike.md"
STRUCTURE_ZHENJIU = FIXTURES / "structure_zhenjiu.md"
STRUCTURE_RENWEN = FIXTURES / "structure_renwen.md"

NEIKE_VERSION = "neike.v1.8ea7bc991418"
ZHENJIU_VERSION = "zhenjiu.v1.e267e196ca45"
RENWEN_VERSION = "renwen.v1.20340ad679a8"

REQUIRED_NEIKE = {
    "disease_concept",
    "disease_pathogenesis",
    "treatment_principle",
    "syndrome_formula",
    "versioned_classification",
}
REQUIRED_ZHENJIU = {
    "meridian_overview",
    "acupoint_location",
    "acupoint_indication",
    "acupoint_operation",
    "acupoint_caution",
}
REQUIRED_RENWEN = {
    "ethics_principle",
    "regulation_fact",
    "ethics_scenario",
}


@pytest.fixture(scope="module")
def neike_cards():
    return extract_neike_cards(
        NEIKE_MD.read_text(encoding="utf-8"),
        document_version=NEIKE_VERSION,
        chunk_id_prefix="neike.golden",
        generation_batch_id="p5t04-neike-golden",
        pdf_page_index=3,
        printed_page_label="8",
    )


@pytest.fixture(scope="module")
def zhenjiu_cards():
    return extract_zhenjiu_cards(
        ZHENJIU_MD.read_text(encoding="utf-8"),
        document_version=ZHENJIU_VERSION,
        chunk_id_prefix="zhenjiu.golden",
        generation_batch_id="p5t04-zhenjiu-golden",
        pdf_page_index=5,
        printed_page_label="30",
    )


@pytest.fixture(scope="module")
def renwen_cards():
    return extract_renwen_cards(
        RENWEN_MD.read_text(encoding="utf-8"),
        document_version=RENWEN_VERSION,
        chunk_id_prefix="renwen.golden",
        generation_batch_id="p5t04-renwen-golden",
        pdf_page_index=1,
        printed_page_label="4",
    )


def test_neike_risk_types_registered() -> None:
    for ctype in REQUIRED_NEIKE:
        assert ctype in CARD_TYPE_DEFAULT_RISK


def test_zhenjiu_risk_types_registered() -> None:
    for ctype in REQUIRED_ZHENJIU:
        assert ctype in CARD_TYPE_DEFAULT_RISK
    assert CARD_TYPE_DEFAULT_RISK["acupoint_location"][0] == "high"
    assert CARD_TYPE_DEFAULT_RISK["acupoint_operation"][0] == "high"
    assert CARD_TYPE_DEFAULT_RISK["acupoint_caution"][0] == "critical"


def test_renwen_risk_types_registered() -> None:
    for ctype in REQUIRED_RENWEN | {"history_fact"}:
        assert ctype in CARD_TYPE_DEFAULT_RISK
    assert CARD_TYPE_DEFAULT_RISK["regulation_fact"][0] == "high"
    assert CARD_TYPE_DEFAULT_RISK["versioned_classification"][0] == "critical"


def test_neike_golden_covers_required_templates(neike_cards) -> None:
    types = {c.card_type for c in neike_cards}
    assert REQUIRED_NEIKE.issubset(types)
    assert len(neike_cards) >= 8


def test_neike_feilao_core_fields(neike_cards) -> None:
    concept = next(
        c for c in neike_cards if c.card_type == "disease_concept" and "肺痨" in c.question
    )
    patho = next(
        c for c in neike_cards if c.card_type == "disease_pathogenesis" and "肺痨" in c.question
    )
    principle = next(
        c for c in neike_cards if c.card_type == "treatment_principle" and "肺痨" in c.question
    )
    syndromes = [c for c in neike_cards if c.card_type == "syndrome_formula"]
    assert "传染" in concept.answer or "慢性" in concept.answer
    assert "阴虚" in patho.answer
    assert "补虚" in principle.answer or "抗痨" in principle.answer
    assert any("肺阴亏损" in c.question and "月华丸" in c.answer for c in syndromes)
    assert any("虚火灼肺" in c.question for c in syndromes)
    assert all(c.risk_level == RiskLevel.HIGH for c in syndromes)
    assert concept.document_key == "neike"
    assert concept.document_version == NEIKE_VERSION
    assert concept.generator == GENERATOR
    assert concept.prompt_version == PROMPT_VERSION


def test_neike_versioned_classification(neike_cards) -> None:
    versions = [c for c in neike_cards if c.card_type == "versioned_classification"]
    assert len(versions) >= 2
    assert any("十版教材" in c.question for c in versions)
    assert any("人卫三版" in c.question or "五版" in c.question for c in versions)
    assert all(c.risk_level == RiskLevel.CRITICAL for c in versions)
    assert all("multi_version" in c.risk_flags for c in versions)
    assert all(c.tags and any("教材" in t for t in c.tags) for c in versions)


def test_zhenjiu_golden_covers_required_templates(zhenjiu_cards) -> None:
    types = {c.card_type for c in zhenjiu_cards}
    assert REQUIRED_ZHENJIU.issubset(types)
    assert len(zhenjiu_cards) >= 8


def test_zhenjiu_acupoint_and_risk(zhenjiu_cards) -> None:
    loc = next(
        c for c in zhenjiu_cards if c.card_type == "acupoint_location" and "足三里" in c.question
    )
    ind = next(
        c for c in zhenjiu_cards if c.card_type == "acupoint_indication" and "足三里" in c.question
    )
    op = next(
        c for c in zhenjiu_cards if c.card_type == "acupoint_operation" and "足三里" in c.question
    )
    cautions = [c for c in zhenjiu_cards if c.card_type == "acupoint_caution"]
    meridians = [c for c in zhenjiu_cards if c.card_type == "meridian_overview"]
    assert "犊鼻" in loc.answer and "3寸" in loc.answer
    assert "胃痛" in ind.answer or "腹胀" in ind.answer
    assert "直刺" in op.answer
    assert any("中极" in c.question or "孕妇" in c.answer or "深刺" in c.answer for c in cautions)
    assert meridians
    assert loc.risk_level == RiskLevel.HIGH
    assert op.risk_level == RiskLevel.HIGH
    assert all(c.risk_level == RiskLevel.CRITICAL for c in cautions)
    assert loc.document_key == "zhenjiu"
    assert loc.document_version == ZHENJIU_VERSION


def test_renwen_golden_covers_required_templates(renwen_cards) -> None:
    types = {c.card_type for c in renwen_cards}
    assert REQUIRED_RENWEN.issubset(types)
    assert len(renwen_cards) >= 6


def test_renwen_ethics_and_regulation(renwen_cards) -> None:
    principles = [c for c in renwen_cards if c.card_type == "ethics_principle"]
    regs = [c for c in renwen_cards if c.card_type == "regulation_fact"]
    scenarios = [c for c in renwen_cards if c.card_type == "ethics_scenario"]
    assert any("不伤害" in c.question or "不伤害" in c.answer for c in principles)
    assert any("知情同意" in c.question or "知情同意" in c.answer for c in principles)
    assert regs
    assert any("2022" in c.answer or any("2022" in t for t in c.tags) for c in regs)
    assert any("医师法" in c.answer or any("医师法" in t for t in c.tags) for c in regs)
    assert all(c.risk_level == RiskLevel.HIGH for c in regs)
    assert all("regulation_or_statute" in c.risk_flags for c in regs)
    assert scenarios
    assert all(c.risk_level == RiskLevel.HIGH for c in scenarios)
    assert all(c.document_version == RENWEN_VERSION for c in renwen_cards)
    assert all(c.document_key == "renwen" for c in renwen_cards)


def test_all_golden_cards_pass_v2_gate(neike_cards, zhenjiu_cards, renwen_cards) -> None:
    for card in [*neike_cards, *zhenjiu_cards, *renwen_cards]:
        model = validate_candidate_card_v2(card)
        assert model.chunk_ids
        assert model.sources
        assert model.pdf_page_indexes
        assert model.content_hash


def test_structure_fixtures_also_extract_basic_cards() -> None:
    neike = extract_neike_zhenjiu_renwen_cards(
        STRUCTURE_NEIKE.read_text(encoding="utf-8"),
        book_template="neike",
        document_version="neike.fixture.v1",
    )
    zhenjiu = extract_neike_zhenjiu_renwen_cards(
        STRUCTURE_ZHENJIU.read_text(encoding="utf-8"),
        book_template="zhenjiu",
        document_version="zhenjiu.fixture.v1",
    )
    renwen = extract_neike_zhenjiu_renwen_cards(
        STRUCTURE_RENWEN.read_text(encoding="utf-8"),
        book_template="renwen",
        document_version="renwen.fixture.v1",
    )
    assert any(c.card_type in {"disease_concept", "syndrome_formula"} for c in neike)
    assert any(c.card_type in {"acupoint_location", "meridian_overview"} for c in zhenjiu)
    assert any(c.card_type == "ethics_principle" for c in renwen)


def test_dispatch_rejects_unknown_template() -> None:
    with pytest.raises(ValueError):
        extract_neike_zhenjiu_renwen_cards(
            "# x\n",
            book_template="fangji",
            document_version="fangji.v1.x",
        )
