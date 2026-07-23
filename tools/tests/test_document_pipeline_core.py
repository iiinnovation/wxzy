"""Key-free unit tests for tools.document_pipeline pure helpers."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from tools.document_pipeline.budget import (
    MINERU_DAILY_FILE_BUDGET,
    MINERU_DAILY_PAGE_BUDGET,
    corpus_budget_assessment,
    estimate_split_count,
    fresh_budget,
)
from tools.document_pipeline.clean import clean_markdown
from tools.document_pipeline.generation import parse_html_tables, stable_id
from tools.document_pipeline.http_client import http_json, redact_url
from tools.document_pipeline.inventory import planned_corpus_summary, planned_document_keys
from tools.document_pipeline.pages import parse_pages
from tools.document_pipeline.paths import CORPUS_PAGE_TOTAL, DOCUMENT_KEYS
from tools.document_pipeline.raw import RawError, is_safe_zip_member, unpack_zip
from tools.document_pipeline.structure import load_content_list, page_number


def test_parse_pages_ranges_and_dedup() -> None:
    assert parse_pages("5-6,20,5,40-41") == [5, 6, 20, 40, 41]


def test_parse_pages_rejects_inverted_range() -> None:
    with pytest.raises(SystemExit, match="invalid page range"):
        parse_pages("10-3")


def test_clean_markdown_ocr_and_header_noise() -> None:
    md = "\n".join(
        [
            "中医考研 学朝 笔记",
            "",
            "粳镶 三合",
            "咬咀",
            "/ 123",
            "正文保留 学朝笔记",
            "",
        ]
    )
    result = clean_markdown(md)
    cleaned = result["cleaned_md"]
    # Header line is corrected then stripped; body OCR corrections remain.
    assert "粳米" in cleaned
    assert "㕮咀" in cleaned
    assert "正文保留 学霸笔记" in cleaned
    assert "中医考研" not in cleaned
    assert result["removed_header_count"] >= 1
    assert result["removed_page_number_count"] >= 1
    assert any(c["from"] == "粳镶" for c in result["corrections"])
    assert any(c["from"] == "学朝笔记" for c in result["corrections"])


def test_page_number_and_content_list(tmp_path: Path) -> None:
    assert page_number("3") == 3
    assert page_number(None) is None
    assert page_number(True) is None

    path = tmp_path / "x_content_list.json"
    path.write_text(
        json.dumps([{"type": "text", "page_idx": 0}, {"type": "table", "page_idx": "1"}]),
        encoding="utf-8",
    )
    items = load_content_list(path)
    assert len(items) == 2
    assert page_number(items[1]["page_idx"]) == 1


def test_zip_member_safety_and_enforce(tmp_path: Path) -> None:
    assert is_safe_zip_member("full.md")
    assert not is_safe_zip_member("../evil.txt")
    assert not is_safe_zip_member("/abs/path")

    zip_path = tmp_path / "ok.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("full.md", "# hi\n")
    names = unpack_zip(zip_path, tmp_path / "out", enforce_safe_members=True)
    assert "full.md" in names
    assert (tmp_path / "out" / "full.md").is_file()

    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises((ValueError, RawError), match="unsafe zip member"):
        unpack_zip(bad_zip, tmp_path / "bad_out", enforce_safe_members=True)


def test_http_json_uses_injectable_transport() -> None:
    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> tuple[int, bytes]:
        assert method == "GET"
        assert "Authorization" in headers
        assert timeout == 12
        return 200, b'{"code":0,"data":{"ok":true}}'

    status, payload = http_json(
        "GET",
        "https://example.test/api",
        token="secret-token",
        timeout=12,
        transport=transport,
    )
    assert status == 200
    assert payload == {"code": 0, "data": {"ok": True}}
    assert redact_url("https://oss.example/a.zip?Signature=abc&Expires=1") == (
        "https://oss.example/a.zip"
    )


def test_budget_accounting_and_corpus_assessment() -> None:
    assert MINERU_DAILY_FILE_BUDGET == 5000
    assert MINERU_DAILY_PAGE_BUDGET == 1000
    snap = fresh_budget(file_budget=5000, page_budget=1000)
    assert snap.can_accept(files=35, pages=704)
    next_snap = snap.reserve(files=6, pages=150)
    assert next_snap.files_used == 6
    assert next_snap.pages_used == 150
    with pytest.raises(ValueError, match="budget exceeded"):
        next_snap.reserve(files=1, pages=900)

    assessment = corpus_budget_assessment(page_total=CORPUS_PAGE_TOTAL)
    assert assessment["page_total"] == 704
    assert assessment["fits_file_budget_one_day"] is True
    assert assessment["fits_page_budget_one_day"] is True
    assert assessment["bottleneck"] == "pages"
    assert estimate_split_count(704, target_pages_per_split=25) == 29


def test_inventory_planned_keys() -> None:
    keys = planned_document_keys()
    assert len(keys) == 7
    assert set(keys) == set(DOCUMENT_KEYS)
    summary = planned_corpus_summary()
    assert summary["page_total"] == 704
    assert summary["document_count"] == 7


def test_generation_helpers_still_exported() -> None:
    first = stable_id("中医内科学", "肺痨", "肺痨的基本病机是什么？")
    assert first == stable_id("中医内科学", "肺痨", "肺痨的基本病机是什么？")
    tables = parse_html_tables("<table><tr><th>方名</th></tr><tr><td>桂枝汤</td></tr></table>")
    assert tables == [[["方名"], ["桂枝汤"]]]
