from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.quality_checks import (
    check_json_files,
    check_markdown_links,
    check_test_directories,
)

ROOT = Path(__file__).resolve().parents[2]


def test_json_check_rejects_invalid_json_and_duplicate_keys(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.json"
    duplicate = tmp_path / "duplicate.json"
    valid.write_text('{"ok": true}\n', encoding="utf-8")
    invalid.write_text('{"broken": }\n', encoding="utf-8")
    duplicate.write_text('{"same": 1, "same": 2}\n', encoding="utf-8")

    result = check_json_files([valid, invalid, duplicate])

    assert not result.ok
    assert result.checked == 3
    assert len(result.errors) == 2
    assert any("duplicate key" in error for error in result.errors)


def test_markdown_check_detects_missing_local_target(tmp_path: Path) -> None:
    existing = tmp_path / "existing.md"
    document = tmp_path / "README.md"
    existing.write_text("# Existing\n", encoding="utf-8")
    document.write_text(
        "[ok](existing.md) [missing](missing.md) [external](https://example.test)\n",
        encoding="utf-8",
    )

    result = check_markdown_links([document], root=tmp_path)

    assert not result.ok
    assert len(result.errors) == 1
    assert "missing.md" in result.errors[0]


def test_test_directory_check_fails_when_a_suite_is_missing(tmp_path: Path) -> None:
    server_tests = tmp_path / "server-tests"
    tool_tests = tmp_path / "tool-tests"
    server_tests.mkdir()
    tool_tests.mkdir()
    (server_tests / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    result = check_test_directories([server_tests, tool_tests])

    assert not result.ok
    assert result.checked == 1
    assert str(tool_tests) in result.errors[0]


def test_quality_check_cli_returns_nonzero_for_bad_json(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "quality_checks.py"), "json", str(invalid)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "FAILED" in result.stderr
