"""Unit tests for chapter-aware PDF split (DOC-002). No private PDFs required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.document_pipeline.split import (
    SplitError,
    build_page_map,
    coverage_report,
    detect_chapter_starts,
    make_split_id,
    plan_document_splits,
    plan_page_ranges,
    run_split_corpus,
    split_document,
    write_split_pdfs,
)


def test_plan_fallback_windows_cover_exactly() -> None:
    ranges = plan_page_ranges(70)
    report = coverage_report(70, ranges)
    assert report["exact"] is True
    assert all(r["page_count"] <= 30 for r in ranges)
    assert all(r["page_count"] >= 20 for r in ranges)
    assert ranges[0]["page_start"] == 1
    assert ranges[-1]["page_end"] == 70


def test_plan_chapter_boundaries_and_subsplit() -> None:
    ranges = plan_page_ranges(149, chapter_starts=[1, 30, 80, 120])
    report = coverage_report(149, ranges)
    assert report["exact"] is True
    # First chapter is short enough to stay intact.
    assert ranges[0] == {
        "page_start": 1,
        "page_end": 29,
        "page_count": 29,
        "boundary_reason": "chapter",
        "chapter_title": None,
    }
    # Long chapter starting at 30 is subsplit.
    assert any(r["boundary_reason"] == "chapter_subsplit" for r in ranges)
    starts = {r["page_start"] for r in ranges}
    assert 30 in starts
    assert 80 in starts
    assert 120 in starts


def test_plan_rejects_out_of_range_chapter_start() -> None:
    with pytest.raises(SplitError, match="out of range"):
        plan_page_ranges(10, chapter_starts=[1, 12])


def test_make_split_id_and_page_map_stable() -> None:
    split_id = make_split_id("neike.v1.8ea7bc991418", 1, 25)
    assert split_id == "neike.v1.8ea7bc991418.p0001-0025"
    mapping = build_page_map(page_start=5, page_end=7)
    assert mapping == [
        {
            "split_page_index": 0,
            "source_pdf_page_index": 4,
            "source_pdf_page_number": 5,
            "printed_page_label": None,
            "mapping_confidence": 1.0,
        },
        {
            "split_page_index": 1,
            "source_pdf_page_index": 5,
            "source_pdf_page_number": 6,
            "printed_page_label": None,
            "mapping_confidence": 1.0,
        },
        {
            "split_page_index": 2,
            "source_pdf_page_index": 6,
            "source_pdf_page_number": 7,
            "printed_page_label": None,
            "mapping_confidence": 1.0,
        },
    ]


def test_detect_chapter_starts_with_injectable_text() -> None:
    texts = {
        1: "前言\n",
        2: "目录\n第一章 概论 ..... 1\n",
        5: "第一章 概论\n正文",
        40: "第二章 阴阳\n正文",
        41: "普通段落\n",
    }

    def page_text(_path: Path, page: int) -> str:
        return texts.get(page, f"正文 {page}")

    starts = detect_chapter_starts(
        Path("/tmp/unused.pdf"),
        page_count=50,
        page_text_fn=page_text,
    )
    assert starts == [5, 40]


def test_write_split_pdfs_uses_extract_fn_and_enforces_size(tmp_path: Path) -> None:
    plan = plan_document_splits(
        document_key="demo",
        document_version="demo.v1.abc",
        source_file_name="demo.pdf",
        source_sha256="deadbeef",
        page_count=40,
        chapter_starts=[],
    )
    source = tmp_path / "demo.pdf"
    source.write_bytes(b"%PDF-fake")
    written: list[tuple[int, int]] = []

    def extract(src: Path, pages: list[int], out: Path) -> dict:
        assert src == source
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 100)
        written.append((pages[0], pages[-1]))
        return {
            "output_pages": len(pages),
            "output_size_bytes": 100,
        }

    result = write_split_pdfs(
        plan,
        source_path=source,
        root=tmp_path,
        extract_fn=extract,
        max_split_bytes=1000,
    )
    assert result["coverage"]["exact"] is True
    assert written
    assert all("output_sha256" in s for s in result["splits"])
    assert all(s["output_size_bytes"] == 100 for s in result["splits"])

    def extract_too_big(src: Path, pages: list[int], out: Path) -> dict:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"y" * 50)
        return {"output_pages": len(pages), "output_size_bytes": 999999}

    with pytest.raises(SplitError, match="exceeds max_split_bytes"):
        write_split_pdfs(
            plan,
            source_path=source,
            root=tmp_path,
            extract_fn=extract_too_big,
            max_split_bytes=1000,
        )


def test_run_split_corpus_plan_only_from_inventory(tmp_path: Path) -> None:
    inv_dir = tmp_path / "data" / "document-pipeline" / "inventory"
    inv_dir.mkdir(parents=True)
    docs = [
        {
            "document_key": "renwen",
            "document_version": "renwen.v1.abc",
            "source_file_name": "人文.pdf",
            "source_relpath": "docs/人文.pdf",
            "source_sha256": "aa",
            "page_count": 39,
        },
        {
            "document_key": "jichu",
            "document_version": "jichu.v1.bb",
            "source_file_name": "基础.pdf",
            "source_relpath": "docs/基础.pdf",
            "source_sha256": "bb",
            "page_count": 50,
        },
    ]
    inv_path = inv_dir / "documents.v1.json"
    inv_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "document_count": 2,
                "page_total": 89,
                "documents": docs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    (source_dir / "人文.pdf").write_bytes(b"%PDF-1")
    (source_dir / "基础.pdf").write_bytes(b"%PDF-2")

    def page_count(path: Path) -> int:
        return 39 if "人文" in path.name else 50

    summary = run_split_corpus(
        root=tmp_path,
        inventory_path=inv_path,
        source_dir=source_dir,
        detect_chapters=False,
        write_pdfs=False,
        page_count_fn=page_count,
    )
    assert summary["document_count"] == 2
    assert summary["page_total"] == 89
    assert summary["split_total"] >= 2
    # Manifests written under splits/
    for doc in summary["documents"]:
        manifest_path = tmp_path / doc["manifest_relpath"]
        assert manifest_path.is_file()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["coverage"]["exact"] is True
        # publication-safe: no absolute paths
        blob = json.dumps(payload, ensure_ascii=False)
        assert str(tmp_path) not in blob
        assert "/Users/" not in blob


def test_split_document_with_injected_chapters(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF")
    doc = {
        "document_key": "demo",
        "document_version": "demo.v1.x",
        "source_file_name": "book.pdf",
        "source_sha256": "cc",
        "page_count": 55,
    }

    def extract(src: Path, pages: list[int], out: Path) -> dict:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"pdf")
        return {"output_pages": len(pages), "output_size_bytes": 3}

    manifest = split_document(
        document=doc,
        source_path=source,
        root=tmp_path,
        chapter_starts=[1, 26],
        detect_chapters=False,
        extract_fn=extract,
        write_pdfs=True,
        max_split_bytes=1000,
    )
    assert manifest["coverage"]["exact"] is True
    assert manifest["chapter_starts"] == [1, 26]
    assert all(Path(tmp_path / s["output_relpath"]).is_file() for s in manifest["splits"])


def test_soft_max_avoids_awkward_near_max_split() -> None:
    ranges = plan_page_ranges(31)
    assert len(ranges) == 1
    assert ranges[0]["page_count"] == 31
    assert coverage_report(31, ranges)["exact"] is True
