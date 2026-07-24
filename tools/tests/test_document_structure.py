"""P3-T07 chapter tree, ContentBlock, and stable chunk id tests."""

from __future__ import annotations

import json
from pathlib import Path

from tools.document_pipeline.structure import (
    BOOK_TEMPLATE_KEYS,
    STRUCTURE_PIPELINE_VERSION,
    build_chapter_tree,
    classify_heading,
    default_structured_dir,
    extract_markdown_headings,
    stable_chunk_id,
    structure_document,
    write_structured_artifacts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "document_pipeline" / "fixtures"


def _load_template(key: str) -> tuple[str, list[dict], dict]:
    stem = f"structure_{key}"
    md = (FIXTURES / f"{stem}.md").read_text(encoding="utf-8")
    items = json.loads((FIXTURES / f"{stem}_content_list.json").read_text(encoding="utf-8"))
    meta = json.loads((FIXTURES / f"{stem}.meta.json").read_text(encoding="utf-8"))
    return md, items, meta


def test_seven_book_template_fixtures_structure() -> None:
    assert len(BOOK_TEMPLATE_KEYS) == 7
    for key in BOOK_TEMPLATE_KEYS:
        md, items, meta = _load_template(key)
        result = structure_document(
            cleaned_md=md,
            document_version_id=meta["document_version_id"],
            content_list=items,
            book_template=key,
            source_pdf_page_start=meta["source_pdf_page_start"],
            expected_page_count=meta["expected_pages"],
        )
        assert result["pipeline_version"] == STRUCTURE_PIPELINE_VERSION
        assert result["book_template"] == key
        assert result["content_block_count"] >= 1
        assert result["page_map_coverage"]["complete"] is True
        # every block can point back to raw/source pages when map complete
        with_pages = result["metrics"]["blocks_with_source_pages"]
        assert with_pages == result["content_block_count"]
        for block in result["content_blocks"]:
            assert block["id"]
            assert block["source_pdf_pages"]
            assert "raw_text_ref" in block
            assert block["raw_text_ref"]["source_pdf_pages"] == block["source_pdf_pages"]
            assert block["pipeline_version"] == STRUCTURE_PIPELINE_VERSION
            if block["block_type"] == "table":
                assert "table_rows" in block
                assert isinstance(block["table_rows"], list)
        # page records link block ids
        all_ids = {b["id"] for b in result["content_blocks"]}
        for page in result["page_records"]:
            for bid in page["content_block_ids"]:
                assert bid in all_ids
        # stable chapter method/confidence present
        assert result["chapter_boundaries"]
        for b in result["chapter_boundaries"]:
            assert b.get("method")
            assert "confidence" in b


def test_low_confidence_chapter_not_silently_reassigned() -> None:
    md = (FIXTURES / "structure_low_confidence.md").read_text(encoding="utf-8")
    items = json.loads(
        (FIXTURES / "structure_low_confidence_content_list.json").read_text(encoding="utf-8")
    )
    meta = json.loads((FIXTURES / "structure_low_confidence.meta.json").read_text(encoding="utf-8"))
    result = structure_document(
        cleaned_md=md,
        document_version_id=meta["document_version_id"],
        content_list=items,
        source_pdf_page_start=meta["source_pdf_page_start"],
        expected_page_count=meta["expected_pages"],
    )
    low = [c for c in result["chapter_boundaries"] if c.get("needs_review")]
    assert low, "expected at least one low-confidence boundary"
    # active high-confidence path after uncertain heading should still be 第一章
    assigned_chapters = [
        c
        for c in result["chapter_boundaries"]
        if c.get("assignment") == "assigned" and not c.get("needs_review")
    ]
    assert any("第一章" in str(c.get("title") or "") for c in assigned_chapters)
    # uncertain boundary must not rewrite active_path_after to only the vague title
    for c in low:
        active = c.get("active_path_after") or []
        assert "奇怪句子" not in "".join(active)
        # path may include the uncertain title for the boundary itself, but active path freezes
        assert any("第一章" in p for p in active) or active == []
    # later clear section can assign again
    assert any(
        c.get("role") == "section" and c.get("assignment") == "assigned"
        for c in result["chapter_boundaries"]
    )


def test_stable_chunk_id_repeatable_and_sensitive() -> None:
    a = stable_chunk_id(
        "doc.v1",
        block_type="table",
        source_pdf_pages=[20],
        ordinal=1,
        content="<table>a</table>",
    )
    b = stable_chunk_id(
        "doc.v1",
        block_type="table",
        source_pdf_pages=[20],
        ordinal=1,
        content="<table>a</table>",
    )
    c = stable_chunk_id(
        "doc.v1",
        block_type="table",
        source_pdf_pages=[20],
        ordinal=1,
        content="<table>b</table>",
    )
    assert a == b
    assert a != c
    assert a.startswith("table-")


def test_classify_heading_roles() -> None:
    assert classify_heading("第九章 解表剂")["role"] == "chapter"
    assert classify_heading("第一节 清气分热剂")["role"] == "section"
    assert classify_heading("中医考研 学霸 笔记")["role"] == "noise"
    pipe = classify_heading("第四部分 方剂学 | 第九章 解表剂")
    assert pipe["role"] == "chapter"
    assert pipe["confidence"] >= 0.9
    unknown = classify_heading("可能是标题也可能不是的奇怪句子没有章节目")
    assert unknown["confidence"] < 0.6


def test_write_structured_artifacts_outside_raw(tmp_path: Path) -> None:
    md, items, meta = _load_template("fangji")
    result = structure_document(
        cleaned_md=md,
        document_version_id=meta["document_version_id"],
        content_list=items,
        book_template="fangji",
        source_pdf_page_start=meta["source_pdf_page_start"],
        expected_page_count=meta["expected_pages"],
    )
    # simulate raw tree source mapping
    raw_md = tmp_path / "raw" / "job1" / "unzipped" / "full.md"
    raw_md.parent.mkdir(parents=True)
    raw_md.write_text(md, encoding="utf-8")
    out_dir = default_structured_dir(raw_md)
    assert "structured" in out_dir.parts
    assert "raw" not in out_dir.parts
    written = write_structured_artifacts(result, out_dir)
    assert Path(written["content_blocks"]).is_file()
    lines = Path(written["content_blocks"]).read_text(encoding="utf-8").strip().splitlines()
    assert lines
    first = json.loads(lines[0])
    assert first["id"]
    assert first["source_pdf_pages"]
    # table structure preserved
    tables = [json.loads(line) for line in lines if json.loads(line)["block_type"] == "table"]
    assert tables
    assert tables[0]["table_rows"]


def test_structure_idempotent_ids() -> None:
    md, items, meta = _load_template("neike")
    kwargs = dict(
        cleaned_md=md,
        document_version_id=meta["document_version_id"],
        content_list=items,
        book_template="neike",
        source_pdf_page_start=meta["source_pdf_page_start"],
        expected_page_count=meta["expected_pages"],
    )
    a = structure_document(**kwargs)
    b = structure_document(**kwargs)
    assert [x["id"] for x in a["content_blocks"]] == [x["id"] for x in b["content_blocks"]]


def test_build_chapter_tree_keeps_method() -> None:
    md, _, _ = _load_template("jichu")
    heads = extract_markdown_headings(md)
    tree = build_chapter_tree(md_headings=heads, cl_headings=[])
    assert tree
    assert all("method" in n and "confidence" in n for n in tree)
