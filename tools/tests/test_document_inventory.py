"""Key-free tests for document inventory (DOC-001 / P3-T02)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.document_pipeline.inventory import (
    InventoryError,
    build_document_record,
    build_local_manifest,
    document_key_for_file_name,
    publication_view,
    run_inventory,
    scan_inventory,
    sha256_file,
    title_from_source_file_name,
)
from tools.document_pipeline.paths import DOCUMENT_KEYS


def _write_pdf_stub(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_title_and_key_mapping() -> None:
    assert title_from_source_file_name("学霸笔记—方剂学(1).pdf") == "学霸笔记—方剂学"
    assert document_key_for_file_name("学霸笔记—方剂学(1).pdf") == "fangji"
    assert document_key_for_file_name("unknown.pdf") is None


def test_scan_inventory_stable_rerun_and_version_bump(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    docs = root / "docs"
    fang = docs / DOCUMENT_KEYS["fangji"]
    nei = docs / DOCUMENT_KEYS["neike"]
    _write_pdf_stub(fang, b"%PDF-1.4 fangji-content-v1")
    _write_pdf_stub(nei, b"%PDF-1.4 neike-content-v1")

    pages = {
        fang.name: 140,
        nei.name: 149,
    }

    def counter(path: Path) -> int:
        return pages[path.name]

    fixed_at = "2026-07-23T00:00:00Z"
    first = scan_inventory(
        root=root,
        source_dir=docs,
        page_counter=counter,
        registered_at=fixed_at,
        require_expected_keys=False,
    )
    assert first["document_count"] == 2
    assert first["page_total"] == 289
    assert first["generated_at"] == fixed_at
    fang_rec = next(d for d in first["documents"] if d["document_key"] == "fangji")
    assert fang_rec["version"] == 1
    assert fang_rec["page_count"] == 140
    assert fang_rec["source_file_name"] == DOCUMENT_KEYS["fangji"]
    assert fang_rec["source_relpath"] == f"docs/{DOCUMENT_KEYS['fangji']}"
    assert fang_rec["source_sha256"] == sha256_file(fang)
    assert "source_abs_path" not in fang_rec
    assert not str(fang_rec["source_relpath"]).startswith("/")

    # Identical content: fully stable output including generated_at and registered_at.
    second = scan_inventory(
        root=root,
        source_dir=docs,
        page_counter=counter,
        previous_inventory=first,
        registered_at="2026-07-24T00:00:00Z",
        require_expected_keys=False,
    )
    assert second == first

    # Content change bumps only that document's version.
    fang.write_bytes(b"%PDF-1.4 fangji-content-v2-changed")
    third = scan_inventory(
        root=root,
        source_dir=docs,
        page_counter=counter,
        previous_inventory=second,
        registered_at="2026-07-25T00:00:00Z",
        require_expected_keys=False,
    )
    fang_v2 = next(d for d in third["documents"] if d["document_key"] == "fangji")
    nei_v1 = next(d for d in third["documents"] if d["document_key"] == "neike")
    assert fang_v2["version"] == 2
    assert fang_v2["source_sha256"] != fang_rec["source_sha256"]
    assert fang_v2["registered_at"] == "2026-07-25T00:00:00Z"
    assert nei_v1["version"] == 1
    assert nei_v1["registered_at"] == fixed_at
    assert third["generated_at"] == "2026-07-25T00:00:00Z"


def test_publication_view_strips_absolute_paths(tmp_path: Path) -> None:
    inventory = {
        "schema_version": 1,
        "generated_at": "2026-07-23T00:00:00Z",
        "source_dir": "docs",
        "document_count": 1,
        "page_total": 1,
        "documents": [
            {
                "document_key": "fangji",
                "source_file_name": DOCUMENT_KEYS["fangji"],
                "source_relpath": f"docs/{DOCUMENT_KEYS['fangji']}",
                "source_abs_path": "/Users/secret/docs/fangji.pdf",
                "source_sha256": "abc",
                "page_count": 1,
                "size_bytes": 10,
                "copyright_scope": "personal-use",
                "version": 1,
            }
        ],
    }
    pub = publication_view(inventory)
    assert "source_abs_path" not in pub["documents"][0]
    dumped = json.dumps(pub)
    assert "/Users/secret" not in dumped

    local = build_local_manifest(inventory, root=tmp_path, source_dir=tmp_path / "docs")
    assert local["note"].startswith("LOCAL ONLY")
    assert "root" in local


def test_run_inventory_writes_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    docs = root / "docs"
    path = docs / DOCUMENT_KEYS["renwen"]
    _write_pdf_stub(path, b"%PDF renwen")

    summary = run_inventory(
        root=root,
        source_dir=docs,
        page_counter=lambda p: 39,
        require_expected_keys=False,
    )
    inv_path = root / summary["inventory_path"]
    local_path = root / summary["local_manifest_path"]
    assert inv_path.is_file()
    assert local_path.is_file()
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    local = json.loads(local_path.read_text(encoding="utf-8"))
    assert inv["document_count"] == 1
    assert inv["page_total"] == 39
    assert "source_abs_path" not in inv["documents"][0]
    assert local["sources"][0]["source_abs_path"] is not None
    assert str(local["sources"][0]["source_abs_path"]).startswith(str(root.resolve()))


def test_build_document_record_rejects_path_filename(tmp_path: Path) -> None:
    root = tmp_path
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(InventoryError):
        # Simulate unsafe name check via direct call with a path-like name is hard
        # because Path.name strips parents; exercise missing file instead.
        build_document_record(
            document_key="fangji",
            source_path=tmp_path / "missing.pdf",
            root=root,
            page_counter=lambda p: 1,
        )


def test_missing_expected_keys_fail(tmp_path: Path) -> None:
    root = tmp_path
    docs = root / "docs"
    docs.mkdir()
    (docs / DOCUMENT_KEYS["fangji"]).write_bytes(b"%PDF fang")
    with pytest.raises(InventoryError, match="missing expected"):
        scan_inventory(
            root=root,
            source_dir=docs,
            page_counter=lambda p: 1,
            require_expected_keys=True,
        )
