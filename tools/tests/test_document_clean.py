"""P3-T06 clean.v2 rules, replace audit, and page mapping tests."""

from __future__ import annotations

import json
from pathlib import Path

from tools.document_pipeline.clean import (
    CLEAN_RULE_VERSION,
    clean_markdown,
    write_cleaned_markdown,
)
from tools.document_pipeline.page_mapping import (
    build_page_map_from_content_list,
    enrich_page_map_from_content_list_path,
    normalize_printed_page_label,
    page_map_coverage,
)
from tools.document_pipeline.split import build_page_map
from tools.document_pipeline.structure import load_content_list

FIXTURES = Path(__file__).resolve().parents[1] / "document_pipeline" / "fixtures"


def test_clean_v2_fixes_fixed_ocr_errors_from_fixture() -> None:
    md = (FIXTURES / "clean_v2_sample.md").read_text(encoding="utf-8")
    expected = json.loads((FIXTURES / "clean_v2_expected.json").read_text(encoding="utf-8"))
    first = clean_markdown(md)
    cleaned = first["cleaned_md"]
    assert first["rule_version"] == "clean.v2"
    for s in expected["must_contain"]:
        assert s in cleaned, s
    lines = {ln.strip() for ln in cleaned.splitlines()}
    for banned in expected["must_not_contain_lines"]:
        assert banned not in lines, banned
    applied = set(first["rule_ids_applied"])
    for rid in expected["rule_ids"]:
        assert rid in applied, rid
    # every replacement has rule_id + before/after
    assert first["replacements"]
    for rep in first["replacements"]:
        assert rep["rule_id"]
        assert "before" in rep and "after" in rep
        assert rep["count"] >= 1
    # corrections remain backward compatible keys
    assert any(
        c["from"] == "粳镶" and c["to"] == "粳米" and c["rule_id"] for c in first["corrections"]
    )


def test_clean_v2_idempotent() -> None:
    md = (FIXTURES / "clean_v2_sample.md").read_text(encoding="utf-8")
    first = clean_markdown(md)
    second = clean_markdown(first["cleaned_md"])
    assert second["cleaned_md"] == first["cleaned_md"]
    assert second["output_sha256"] == first["output_sha256"]
    # second pass should not re-apply OCR corrections
    assert second["corrections"] == []
    assert second["removed_header_count"] == 0
    assert second["removed_page_number_count"] == 0


def test_page_mapping_separates_pdf_and_printed() -> None:
    items = load_content_list(FIXTURES / "clean_v2_content_list.json")
    base = build_page_map(page_start=20, page_end=22)
    mapping = build_page_map_from_content_list(items, base_page_map=base)
    assert len(mapping) == 3
    cov = page_map_coverage(mapping)
    assert cov["complete"] is True
    assert cov["pdf_coverage"] == 1.0
    assert cov["printed_coverage"] == 1.0

    row0 = mapping[0]
    assert row0["split_page_index"] == 0
    assert row0["source_pdf_page_index"] == 19
    assert row0["source_pdf_page_number"] == 20
    assert row0["printed_page_label"] == "294"
    assert isinstance(row0["printed_page_label"], str)
    assert row0["source_pdf_page_number"] != int(row0["printed_page_label"])

    row1 = mapping[1]
    assert row1["source_pdf_page_number"] == 21
    assert row1["printed_page_label"] == "295"  # normalized from "/ 295"
    assert row1["mapping_confidence"] >= 0.9

    # never collapse printed into source integer identity
    for row in mapping:
        assert "source_pdf_page_index" in row
        assert "source_pdf_page_number" in row
        assert "printed_page_label" in row
        assert "mapping_confidence" in row


def test_page_mapping_100_percent_without_printed_still_complete() -> None:
    # PDF identity only: no page_number items
    items = [
        {"type": "text", "text": "x", "page_idx": 0},
        {"type": "text", "text": "y", "page_idx": 1},
    ]
    mapping = build_page_map_from_content_list(
        items,
        source_pdf_page_start=5,
        expected_page_count=2,
    )
    cov = page_map_coverage(mapping)
    assert cov["complete"] is True
    assert cov["pdf_coverage"] == 1.0
    assert cov["printed_coverage"] == 0.0
    assert mapping[0]["source_pdf_page_number"] == 5
    assert mapping[1]["source_pdf_page_number"] == 6
    assert mapping[0]["printed_page_label"] is None


def test_normalize_printed_page_label() -> None:
    assert normalize_printed_page_label("/ 295") == "295"
    assert normalize_printed_page_label(" 12 ") == "12"
    assert normalize_printed_page_label("") is None
    assert normalize_printed_page_label(None) is None


def test_write_cleaned_with_page_map_sidecar(tmp_path: Path) -> None:
    src = tmp_path / "raw" / "job" / "unzipped" / "full.md"
    src.parent.mkdir(parents=True)
    src.write_text((FIXTURES / "clean_v2_sample.md").read_text(encoding="utf-8"), encoding="utf-8")
    items = load_content_list(FIXTURES / "clean_v2_content_list.json")
    mapping = build_page_map_from_content_list(
        items, source_pdf_page_start=1, expected_page_count=3
    )
    result = write_cleaned_markdown(src, page_map=mapping)
    out = Path(result["out"])
    meta = Path(result["meta"])
    assert out.is_file()
    assert "cleaned" in out.parts
    assert meta.is_file()
    meta_obj = json.loads(meta.read_text(encoding="utf-8"))
    assert meta_obj["rule_version"] == CLEAN_RULE_VERSION
    assert "replacements" in meta_obj
    assert meta_obj["page_map_coverage"]["complete"] is True
    pm_path = out.with_suffix(out.suffix + ".page_map.json")
    assert pm_path.is_file()
    pm = json.loads(pm_path.read_text(encoding="utf-8"))
    assert len(pm["page_map"]) == 3
    # raw unchanged
    assert result["raw_unchanged"] is True


def test_enrich_from_path_matches_inline() -> None:
    path = FIXTURES / "clean_v2_content_list.json"
    a = enrich_page_map_from_content_list_path(
        path, source_pdf_page_start=10, expected_page_count=3
    )
    items = load_content_list(path)
    b = build_page_map_from_content_list(items, source_pdf_page_start=10, expected_page_count=3)
    assert a == b
