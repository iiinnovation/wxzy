"""P3-T08 quality report gate and fail-fixture tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.document_pipeline.quality import (
    QUALITY_PIPELINE_VERSION,
    aggregate_gate_result,
    build_report_summary,
    quality_report_for_dir,
    write_quality_markdown,
)

FIXTURES = Path(__file__).resolve().parents[1] / "document_pipeline" / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def _meta(name: str) -> dict:
    return json.loads((FIXTURES / name / "meta.json").read_text(encoding="utf-8"))


def _report(name: str) -> dict:
    meta = _meta(name)
    return quality_report_for_dir(
        FIXTURES / name,
        sample_key=name,
        expected_pages=meta.get("expected_pages"),
        source_pdf_page_start=meta.get("source_pdf_page_start"),
        gate=True,
    )


def test_missing_page_fixture_fails_gate() -> None:
    report = _report("quality_missing_page")
    assert report["pipeline_version"] == QUALITY_PIPELINE_VERSION
    assert report["terminal_status"] == "fail"
    assert report["ok"] is False
    assert report["exit_code"] == 1
    codes = {r["code"] for r in report["issue_records"]}
    assert "missing_pages" in codes
    assert 1 in (report["page_coverage"].get("missing_pages") or [])


def test_bad_table_fixture_fails_gate() -> None:
    report = _report("quality_bad_table")
    assert report["terminal_status"] == "fail"
    assert report["ok"] is False
    codes = {r["code"] for r in report["issue_records"]}
    assert "bad_tables" in codes
    assert report["metrics"]["bad_table_count"] >= 1


def test_suspicious_ocr_fixture_fails_gate() -> None:
    report = _report("quality_suspicious")
    assert report["terminal_status"] == "fail"
    assert report["ok"] is False
    codes = {r["code"] for r in report["issue_records"]}
    assert "suspicious_ocr" in codes
    assert report["metrics"]["hard_suspicious_hit_count"] >= 1
    patterns = {h["pattern"] for h in report["suspicious_hits"]}
    assert patterns & {"粳镶", "咬咀", "黎黎", "学朝"}


def test_pass_fixture_passes_gate() -> None:
    report = _report("quality_pass")
    assert report["terminal_status"] == "pass"
    assert report["ok"] is True
    assert report["gate_ok"] is True
    assert report["exit_code"] == 0
    assert report["issue_records"] == []
    assert report["page_coverage"]["complete"] is True
    assert report["page_map_coverage"]["complete"] is True
    assert report["metrics"]["bad_table_count"] == 0


def test_summary_does_not_contain_full_source_text() -> None:
    for name in (
        "quality_missing_page",
        "quality_bad_table",
        "quality_suspicious",
        "quality_pass",
    ):
        md = (FIXTURES / name / "full.md").read_text(encoding="utf-8")
        report = _report(name)
        summary = report.get("summary") or build_report_summary(report)
        blob = json.dumps(summary, ensure_ascii=False)
        assert md not in blob
        # no long body dump
        assert len(blob) < max(800, len(md) * 2)
        # markdown write path also must not embed full source
        out = Path("/private/tmp") / f"wxzy-quality-{name}.md"
        write_quality_markdown([report], out)
        written = out.read_text(encoding="utf-8")
        assert md not in written
        # short contexts only for suspicious hits
        for hit in report.get("suspicious_hits") or []:
            assert len(hit.get("context") or "") <= 80


def test_aggregate_gate_nonzero_when_any_fail() -> None:
    reports = [
        _report("quality_pass"),
        _report("quality_suspicious"),
    ]
    agg = aggregate_gate_result(reports)
    assert agg["exit_code"] == 1
    assert agg["any_fail"] is True
    assert agg["all_pass"] is False


def test_cli_quality_report_nonzero_exit(tmp_path: Path) -> None:
    target = FIXTURES / "quality_suspicious"
    out_json = tmp_path / "q.json"
    out_md = tmp_path / "q.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "mineru_validate.py"),
            "quality-report",
            str(target),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--expected-pages",
            "1",
            "--source-pdf-page-start",
            "294",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert out_json.is_file()
    assert out_md.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("exit_code") == 1
    assert payload.get("gate", {}).get("exit_code") == 1


def test_cli_quality_report_pass_exit_zero(tmp_path: Path) -> None:
    target = FIXTURES / "quality_pass"
    out_json = tmp_path / "q.json"
    out_md = tmp_path / "q.md"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "mineru_validate.py"),
            "quality-report",
            str(target),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--expected-pages",
            "2",
            "--source-pdf-page-start",
            "1",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload.get("exit_code") == 0
