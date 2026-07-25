"""P5-T03: zhongyao / fangji template golden tests."""

from __future__ import annotations

import pytest
from tools.document_pipeline.candidate_schema import (
    CARD_TYPE_DEFAULT_RISK,
    RiskLevel,
    validate_candidate_card_v2,
)
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.templates_zhongyao_fangji import (
    GENERATOR,
    PROMPT_VERSION,
    extract_fangji_cards,
    extract_zhongyao_cards,
    extract_zhongyao_fangji_cards,
)

FIXTURES = ROOT / "tools" / "document_pipeline" / "fixtures"
ZHONGYAO_MD = FIXTURES / "templates_zhongyao_golden.md"
FANGJI_MD = FIXTURES / "templates_fangji_golden.md"
STRUCTURE_ZHONGYAO = FIXTURES / "structure_zhongyao.md"
STRUCTURE_FANGJI = FIXTURES / "structure_fangji.md"

ZHONGYAO_VERSION = "zhongyao.v1.e9037a725021"
FANGJI_VERSION = "fangji.v1.0755d148d00a"

REQUIRED_ZHONGYAO = {
    "herb_nature_flavor",
    "herb_function",
    "herb_indication",
    "herb_usage",
    "herb_toxicity_caution",
    "herb_compatibility",
    "herb_contrast",
}
REQUIRED_FANGJI = {
    "formula_compose",
    "formula_function",
    "formula_indication",
    "formula_song",
    "formula_usage_note",
    "formula_compatibility",
}


@pytest.fixture(scope="module")
def zhongyao_cards():
    md = ZHONGYAO_MD.read_text(encoding="utf-8")
    return extract_zhongyao_cards(
        md,
        document_version=ZHONGYAO_VERSION,
        chunk_id_prefix="zhongyao.golden",
        generation_batch_id="p5t03-zhongyao-golden",
        pdf_page_index=2,
        printed_page_label="3",
    )


@pytest.fixture(scope="module")
def fangji_cards():
    md = FANGJI_MD.read_text(encoding="utf-8")
    return extract_fangji_cards(
        md,
        document_version=FANGJI_VERSION,
        chunk_id_prefix="fangji.golden",
        generation_batch_id="p5t03-fangji-golden",
        pdf_page_index=4,
        printed_page_label="12",
    )


def test_zhongyao_risk_types_registered() -> None:
    for ctype in REQUIRED_ZHONGYAO:
        assert ctype in CARD_TYPE_DEFAULT_RISK


def test_fangji_risk_types_registered() -> None:
    for ctype in REQUIRED_FANGJI:
        assert ctype in CARD_TYPE_DEFAULT_RISK
    # legacy formula types remain present
    for ctype in ("formula_compose", "formula_song", "formula_usage_note"):
        level, flags = CARD_TYPE_DEFAULT_RISK[ctype]
        assert level == "high"
        assert flags


def test_zhongyao_golden_covers_required_templates(zhongyao_cards) -> None:
    types = {c.card_type for c in zhongyao_cards}
    assert REQUIRED_ZHONGYAO.issubset(types)
    assert len(zhongyao_cards) >= 10


def test_zhongyao_mahuang_fields(zhongyao_cards) -> None:
    nature = next(c for c in zhongyao_cards if c.card_type == "herb_nature_flavor" and "麻黄" in c.question)
    func = next(c for c in zhongyao_cards if c.card_type == "herb_function" and "麻黄" in c.question)
    ind = next(c for c in zhongyao_cards if c.card_type == "herb_indication" and "麻黄" in c.question)
    usage = next(c for c in zhongyao_cards if c.card_type == "herb_usage" and "麻黄" in c.question)
    caution = next(
        c for c in zhongyao_cards if c.card_type == "herb_toxicity_caution" and "麻黄" in c.question
    )
    compat = next(c for c in zhongyao_cards if c.card_type == "herb_compatibility" and "麻黄" in c.question)

    assert "肺" in nature.answer and "膀胱" in nature.answer
    assert "发汗解表" in func.answer
    assert "风寒感冒" in ind.answer
    assert "2" in usage.answer and "10" in usage.answer
    assert "慎用" in caution.answer or "禁用" in caution.answer
    assert "桂枝" in compat.answer
    assert nature.document_key == "zhongyao"
    assert nature.document_version == ZHONGYAO_VERSION
    assert nature.generator == GENERATOR
    assert nature.prompt_version == PROMPT_VERSION


def test_zhongyao_usage_and_toxicity_risk(zhongyao_cards) -> None:
    usage = [c for c in zhongyao_cards if c.card_type == "herb_usage"]
    tox = [c for c in zhongyao_cards if c.card_type == "herb_toxicity_caution"]
    assert usage
    assert tox
    assert all(c.risk_level == RiskLevel.HIGH for c in usage)
    assert all("dosage_or_usage" in c.risk_flags for c in usage)
    assert all(c.risk_level == RiskLevel.CRITICAL for c in tox)
    assert all("toxicity_or_contraindication" in c.risk_flags for c in tox)
    assert any("细辛" in c.question or "细辛" in (c.section or "") for c in tox)


def test_zhongyao_contrast(zhongyao_cards) -> None:
    contrasts = [c for c in zhongyao_cards if c.card_type == "herb_contrast"]
    assert contrasts
    hit = next(c for c in contrasts if "麻黄" in c.question and "桂枝" in c.question)
    assert "发汗" in hit.answer
    assert hit.risk_level == RiskLevel.MEDIUM


def test_fangji_golden_covers_required_templates(fangji_cards) -> None:
    types = {c.card_type for c in fangji_cards}
    assert REQUIRED_FANGJI.issubset(types)
    assert len(fangji_cards) >= 8


def test_fangji_guizhi_tang(fangji_cards) -> None:
    compose = next(c for c in fangji_cards if c.card_type == "formula_compose" and "桂枝汤" in c.question)
    func = next(c for c in fangji_cards if c.card_type == "formula_function" and "桂枝汤" in c.question)
    ind = next(c for c in fangji_cards if c.card_type == "formula_indication" and "桂枝汤" in c.question)
    song = next(c for c in fangji_cards if c.card_type == "formula_song" and "桂枝汤" in c.question)
    usage = next(c for c in fangji_cards if c.card_type == "formula_usage_note" and "桂枝汤" in c.question)
    compat = next(
        c for c in fangji_cards if c.card_type == "formula_compatibility" and "桂枝汤" in c.question
    )

    assert "桂枝" in compose.answer and "芍药" in compose.answer
    assert compose.answer_points
    assert "解肌发表" in func.answer
    assert "表虚" in ind.answer
    assert "太阳风" in song.answer
    assert "稀粥" in usage.answer or "不宜" in usage.answer
    assert "发中有补" in compat.answer or "邪正" in compat.answer
    assert compose.risk_level == RiskLevel.HIGH
    assert "dosage_or_compose" in compose.risk_flags
    assert song.risk_level == RiskLevel.HIGH
    assert usage.risk_level == RiskLevel.HIGH
    assert compose.document_key == "fangji"
    assert compose.document_version == FANGJI_VERSION


def test_fangji_baihu_tang_core_fields(fangji_cards) -> None:
    names = {c.card_type for c in fangji_cards if "白虎汤" in c.question}
    assert {"formula_compose", "formula_function", "formula_indication", "formula_song"}.issubset(names)
    compose = next(c for c in fangji_cards if c.card_type == "formula_compose" and "白虎汤" in c.question)
    assert "石膏" in compose.answer and "知母" in compose.answer


def test_all_golden_cards_pass_v2_gate(zhongyao_cards, fangji_cards) -> None:
    for card in [*zhongyao_cards, *fangji_cards]:
        model = validate_candidate_card_v2(card)
        assert model.chunk_ids
        assert model.sources
        assert model.pdf_page_indexes
        assert model.content_hash
        assert model.risk_level in {
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }


def test_structure_fixtures_also_extract_basic_cards() -> None:
    zhongyao = extract_zhongyao_fangji_cards(
        STRUCTURE_ZHONGYAO.read_text(encoding="utf-8"),
        book_template="zhongyao",
        document_version="zhongyao.fixture.v1",
    )
    fangji = extract_zhongyao_fangji_cards(
        STRUCTURE_FANGJI.read_text(encoding="utf-8"),
        book_template="fangji",
        document_version="fangji.fixture.v1",
    )
    assert any(c.card_type == "herb_nature_flavor" for c in zhongyao)
    assert any(c.card_type == "herb_function" for c in zhongyao)
    assert any(c.card_type == "formula_compose" for c in fangji)
    assert any(c.card_type == "formula_song" for c in fangji)


def test_dispatch_rejects_unknown_template() -> None:
    with pytest.raises(ValueError):
        extract_zhongyao_fangji_cards(
            "# x\n",
            book_template="jichu",
            document_version="jichu.v1.x",
        )
