"""Unit tests for raw zip integrity and immutability (P3-T05)."""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest
from tools.document_pipeline.clean import clean_markdown, write_cleaned_markdown
from tools.document_pipeline.raw import (
    RawError,
    assert_not_raw_write_target,
    file_fingerprint,
    is_safe_zip_member,
    materialize_raw_from_zip,
    sha256_file,
    unpack_zip,
    verify_zip_integrity,
)


def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_malicious_zip_members_rejected(tmp_path: Path) -> None:
    assert not is_safe_zip_member("../evil.txt")
    assert not is_safe_zip_member("/abs/path")
    assert not is_safe_zip_member("C:\\windows\\x")
    assert is_safe_zip_member("full.md")
    assert is_safe_zip_member("images/a.png")

    bad = _make_zip(tmp_path / "bad.zip", {"../escape.txt": b"x", "full.md": b"# ok\n"})
    with pytest.raises(RawError, match="unsafe zip member"):
        verify_zip_integrity(bad)
    with pytest.raises(RawError, match="unsafe zip member"):
        unpack_zip(bad, tmp_path / "out", enforce_safe_members=True)

    # Absolute-style member
    abs_zip = tmp_path / "abs.zip"
    with zipfile.ZipFile(abs_zip, "w") as zf:
        # ZipFile may normalize; craft via ZipInfo
        info = zipfile.ZipInfo("/etc/passwd")
        zf.writestr(info, b"root")
    with pytest.raises(RawError):
        unpack_zip(abs_zip, tmp_path / "abs_out", enforce_safe_members=True)


def test_corrupt_zip_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.zip"
    path.write_bytes(b"not-a-zip-at-all")
    with pytest.raises(RawError, match="not a valid zip"):
        verify_zip_integrity(path)


def test_materialize_records_hashes_and_is_idempotent(tmp_path: Path) -> None:
    zpath = _make_zip(
        tmp_path / "in.zip",
        {
            "full.md": b"# hello raw\n",
            "doc_content_list.json": b"[]",
        },
    )
    raw_dir = tmp_path / "raw" / "split_a"
    m1 = materialize_raw_from_zip(zpath, raw_dir)
    assert m1["zip_sha256"] == sha256_file(raw_dir / "result.zip")
    assert (raw_dir / "unzipped" / "full.md").is_file()
    assert (raw_dir / "raw_manifest.json").is_file()
    assert m1["output_hashes"]["result.zip"]
    assert any(k.endswith("full.md") for k in m1["output_hashes"])

    fp_zip = file_fingerprint(raw_dir / "result.zip")
    fp_md = file_fingerprint(raw_dir / "unzipped" / "full.md")
    m2 = materialize_raw_from_zip(zpath, raw_dir)
    assert m2["zip_sha256"] == m1["zip_sha256"]
    assert file_fingerprint(raw_dir / "result.zip") == fp_zip
    assert file_fingerprint(raw_dir / "unzipped" / "full.md") == fp_md


def test_sha256_mismatch_rejected(tmp_path: Path) -> None:
    zpath = _make_zip(tmp_path / "in.zip", {"full.md": b"# x\n"})
    with pytest.raises(RawError, match="sha256 mismatch"):
        materialize_raw_from_zip(zpath, tmp_path / "raw" / "b", expected_sha256="0" * 64)


def test_clean_does_not_modify_raw_mtime_or_hash(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "document-pipeline" / "jobs" / "j1" / "raw" / "split_a"
    unzipped = raw_dir / "unzipped"
    unzipped.mkdir(parents=True)
    md = unzipped / "full.md"
    md.write_text("中医考研 学朝 笔记\n\n粳镶 正文\n", encoding="utf-8")
    # settle mtime
    time.sleep(0.01)
    before = file_fingerprint(md)

    result = write_cleaned_markdown(md)
    after = file_fingerprint(md)
    assert after == before
    assert result["raw_unchanged"] is True
    out = Path(result["out"])
    assert out.is_file()
    assert "raw" not in out.parts or out.parts[out.parts.index("raw") :] != out.parts
    # destination should be under cleaned/
    assert "cleaned" in out.parts
    assert "粳米" in out.read_text(encoding="utf-8")
    assert md.read_text(encoding="utf-8") == "中医考研 学朝 笔记\n\n粳镶 正文\n"


def test_clean_refuses_raw_output_path(tmp_path: Path) -> None:
    raw_md = tmp_path / "raw" / "unzipped" / "full.md"
    raw_md.parent.mkdir(parents=True)
    raw_md.write_text("a\n", encoding="utf-8")
    with pytest.raises(RawError, match="raw"):
        write_cleaned_markdown(raw_md, out=raw_md.with_name("full.cleaned.md"))


def test_assert_not_raw_write_target(tmp_path: Path) -> None:
    with pytest.raises(RawError):
        assert_not_raw_write_target(tmp_path / "raw" / "x.md")
    # non-raw is fine (no raise)
    assert_not_raw_write_target(tmp_path / "cleaned" / "x.md")


def test_clean_markdown_hashes_stable() -> None:
    info = clean_markdown("咬咀\n")
    assert info["input_sha256"]
    assert info["output_sha256"]
    assert "㕮咀" in info["cleaned_md"]
    assert info["rule_version"] == "clean.v1"
