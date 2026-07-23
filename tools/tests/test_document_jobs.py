"""Unit tests for MinerU job lifecycle (P3-T04). No real MinerU calls."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from tools.document_pipeline.jobs import (
    JobError,
    JobFileSpec,
    create_job,
    create_job_from_split_manifest,
    download_job,
    job_path,
    load_events,
    load_manifest,
    poll_job,
    redact_for_storage,
    stable_data_id,
    submit_job,
)


def _write_pdf(path: Path, payload: bytes = b"%PDF-1.4 test\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class FakeMinerU:
    """Injectable MinerU client with scripted poll states."""

    def __init__(
        self,
        *,
        states: list[str] | None = None,
        fail_apply: bool = False,
        upload_code: int = 200,
        fail_upload: bool = False,
        batch_id: str = "batch-test-1",
    ) -> None:
        self.states = list(states or ["done"])
        self.fail_apply = fail_apply
        self.upload_code = upload_code
        self.fail_upload = fail_upload
        self.batch_id = batch_id
        self.apply_calls = 0
        self.poll_calls = 0
        self.uploads: list[tuple[str, str]] = []
        self.downloads: list[str] = []
        self._poll_index = 0

    def apply_upload_urls(self, body: dict[str, Any]) -> dict[str, Any]:
        self.apply_calls += 1
        if self.fail_apply:
            raise JobError("apply deliberately failed")
        n = len(body.get("files") or [])
        return {
            "batch_id": self.batch_id,
            "file_urls": [
                f"https://oss.example/upload/{i}?Signature=sig&Expires=99" for i in range(n)
            ],
        }

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        assert batch_id == self.batch_id
        self.poll_calls += 1
        state = self.states[min(self._poll_index, len(self.states) - 1)]
        self._poll_index += 1
        item: dict[str, Any] = {
            "data_id": "split_a",
            "file_name": "a.pdf",
            "state": state,
            "extract_progress": {"extracted_pages": 1, "total_pages": 3},
        }
        if state == "done":
            item["full_zip_url"] = "https://oss.example/result.zip?Signature=zzz&Expires=1"
        if state == "failed":
            item["err_msg"] = "extract failed on page 2"
        return {"code": 0, "data": {"extract_result": [item]}}

    def upload(self, upload_url: str, file_path: Path) -> int:
        self.uploads.append((upload_url, file_path.name))
        if self.fail_upload:
            raise RuntimeError("upload transport error")
        return self.upload_code

    def download(self, url: str, dest: Path) -> None:
        self.downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("full.md", "# fixture\n")
            zf.writestr("content_list.json", "[]")


def test_stable_data_id_and_redaction() -> None:
    assert stable_data_id("neike.v1.abc.p0001-0025") == "neike.v1.abc.p0001-0025"
    assert " " not in stable_data_id("weird name!!")
    redacted = redact_for_storage(
        {
            "full_zip_url": "https://oss.example/a.zip?Signature=abc&Expires=1",
            "nested": {"url": "https://x.test/y?Signature=1"},
            "plain": "keep",
        }
    )
    assert redacted["full_zip_url"] == "https://oss.example/a.zip"
    assert redacted["nested"]["url"] == "https://x.test/y"
    assert redacted["plain"] == "keep"
    assert "?" not in json.dumps(redacted)


def test_create_job_manifest_and_events(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "splits" / "a.pdf")
    manifest = create_job(
        [JobFileSpec(split_id="split_a", source_path=pdf, page_count=3, document_key="renwen")],
        root=tmp_path,
        job_id="job_create_1",
        base_url="https://mineru.test",
    )
    assert manifest["stage"] == "planned"
    assert manifest["file_count"] == 1
    assert manifest["page_total"] == 3
    assert manifest["items"][0]["data_id"] == "split_a"
    assert manifest["items"][0]["source_relpath"] == "splits/a.pdf"
    jdir = job_path("job_create_1", root=tmp_path)
    events = load_events(jdir)
    assert events[0]["type"] == "job_created"
    # publication-facing path is relative, not absolute
    assert not Path(manifest["items"][0]["source_relpath"]).is_absolute()
    assert manifest["items"][0]["source_relpath"] == "splits/a.pdf"


def test_submit_poll_download_happy_path(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "splits" / "a.pdf")
    create_job(
        [JobFileSpec(split_id="split_a", source_path=pdf, page_count=3)],
        root=tmp_path,
        job_id="job_ok",
    )
    jdir = job_path("job_ok", root=tmp_path)
    ledger = tmp_path / "budget.json"
    client = FakeMinerU(states=["waiting", "running", "done"])

    submitted = submit_job(jdir, client, root=tmp_path, budget_ledger_path=ledger)
    assert submitted["stage"] == "uploaded"
    assert submitted["batch_id"] == "batch-test-1"
    assert client.apply_calls == 1
    assert len(client.uploads) == 1
    assert "Signature=" in client.uploads[0][0]
    # signed URL must not land in manifest
    stored = (jdir / "manifest.json").read_text(encoding="utf-8")
    assert "Signature=" not in stored
    assert submitted["budget"]["reserved_files"] == 1
    assert submitted["budget"]["reserved_pages"] == 3
    ledger_data = json.loads(ledger.read_text(encoding="utf-8"))
    assert ledger_data["files_used"] == 1
    assert ledger_data["pages_used"] == 3

    # second submit must not re-apply
    again = submit_job(jdir, client, root=tmp_path, budget_ledger_path=ledger)
    assert client.apply_calls == 1
    assert again["batch_id"] == "batch-test-1"
    ledger_after = json.loads(ledger.read_text(encoding="utf-8"))
    assert ledger_after["files_used"] == 1  # budget not double-charged

    t = [0.0]

    def clock() -> float:
        return t[0]

    def sleep(seconds: float) -> None:
        t[0] += max(seconds, 0.001)

    poll = poll_job(
        jdir,
        client,
        timeout_seconds=30,
        interval_seconds=1,
        clock=clock,
        sleep=sleep,
        max_rounds=10,
    )
    assert poll["timed_out"] is False
    assert poll["manifest"]["stage"] == "done"
    assert client.poll_calls >= 3
    states_seen = [
        e["states"] for e in load_events(jdir) if e.get("type") == "poll_state" and "states" in e
    ]
    flat = [s for row in states_seen for s in row]
    assert "waiting" in flat or "running" in flat
    assert "done" in flat or poll["manifest"]["stage"] == "done"

    finished = download_job(jdir, client, root=tmp_path, results=poll["results"])
    assert finished["downloaded"] is True
    assert finished["items"][0]["zip_sha256"]
    raw = jdir / "raw" / "split_a"
    assert (raw / "result.zip").is_file()
    assert (raw / "unzipped" / "full.md").is_file()
    assert client.downloads
    assert "Signature=" in client.downloads[0]
    stored2 = (jdir / "manifest.json").read_text(encoding="utf-8")
    assert "Signature=" not in stored2

    # idempotent re-download
    downloads_before = len(client.downloads)
    download_job(jdir, client, root=tmp_path, results=poll["results"])
    assert len(client.downloads) == downloads_before


def test_poll_failed_and_timeout_keep_batch_id(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "splits" / "a.pdf")
    create_job(
        [JobFileSpec(split_id="split_a", source_path=pdf, page_count=2)],
        root=tmp_path,
        job_id="job_fail",
    )
    jdir = job_path("job_fail", root=tmp_path)
    ledger = tmp_path / "budget.json"

    failed_client = FakeMinerU(states=["failed"])
    submit_job(jdir, failed_client, root=tmp_path, budget_ledger_path=ledger)
    failed = poll_job(
        jdir,
        failed_client,
        timeout_seconds=10,
        interval_seconds=0,
        max_rounds=2,
        clock=lambda: 0.0,
    )
    assert failed["manifest"]["stage"] == "failed"
    assert failed["manifest"]["batch_id"] == "batch-test-1"
    assert failed["manifest"]["items"][0]["err_msg"]

    # timeout path on a separate job
    create_job(
        [JobFileSpec(split_id="split_a", source_path=pdf, page_count=2)],
        root=tmp_path,
        job_id="job_to",
    )
    j2 = job_path("job_to", root=tmp_path)
    waiting = FakeMinerU(states=["waiting", "running"])
    submit_job(j2, waiting, root=tmp_path, budget_ledger_path=ledger)
    t = [0.0]

    def clock() -> float:
        t[0] += 100.0
        return t[0]

    timed = poll_job(
        j2,
        waiting,
        timeout_seconds=50,
        interval_seconds=0,
        clock=clock,
        max_rounds=10,
    )
    assert timed["timed_out"] is True
    assert timed["manifest"]["stage"] == "timed_out"
    assert timed["manifest"]["batch_id"] == "batch-test-1"
    assert timed["manifest"]["timed_out"] is True
    # resume poll after timeout should still work (batch kept)
    waiting.states = ["done"]
    waiting._poll_index = 0
    resumed = poll_job(
        j2,
        waiting,
        timeout_seconds=30,
        interval_seconds=0,
        max_rounds=2,
        clock=lambda: 0.0,
    )
    assert resumed["manifest"]["stage"] == "done"
    assert resumed["timed_out"] is False


def test_budget_exceeded_blocks_submit(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "splits" / "a.pdf")
    create_job(
        [JobFileSpec(split_id="split_a", source_path=pdf, page_count=50)],
        root=tmp_path,
        job_id="job_budget",
    )
    jdir = job_path("job_budget", root=tmp_path)
    ledger = tmp_path / "budget.json"
    ledger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "file_budget": 10,
                "page_budget": 100,
                "files_used": 10,
                "pages_used": 90,
                "files_remaining": 0,
                "pages_remaining": 10,
            }
        ),
        encoding="utf-8",
    )
    client = FakeMinerU()
    with pytest.raises(JobError, match="budget exceeded"):
        submit_job(jdir, client, root=tmp_path, budget_ledger_path=ledger)
    assert client.apply_calls == 0
    assert load_manifest(jdir)["stage"] == "planned"


def test_create_from_split_manifest(tmp_path: Path) -> None:
    pdf1 = _write_pdf(tmp_path / "data" / "document-pipeline" / "splits" / "v1" / "s1.pdf")
    pdf2 = _write_pdf(tmp_path / "data" / "document-pipeline" / "splits" / "v1" / "s2.pdf")
    split_manifest = {
        "document_key": "renwen",
        "document_version": "renwen.v1.abc",
        "splits": [
            {
                "split_id": "renwen.v1.abc.p0001-0020",
                "output_relpath": "data/document-pipeline/splits/v1/s1.pdf",
                "page_count": 20,
            },
            {
                "split_id": "renwen.v1.abc.p0021-0039",
                "output_relpath": "data/document-pipeline/splits/v1/s2.pdf",
                "page_count": 19,
            },
        ],
    }
    # ensure paths exist relative to root
    assert pdf1.is_file() and pdf2.is_file()
    job = create_job_from_split_manifest(
        split_manifest, root=tmp_path, job_id="job_from_split", limit=1
    )
    assert job["file_count"] == 1
    assert job["page_total"] == 20
    assert job["items"][0]["document_key"] == "renwen"


def test_reject_oversized_batch(tmp_path: Path) -> None:
    files = []
    for i in range(13):
        p = _write_pdf(tmp_path / "splits" / f"f{i}.pdf")
        files.append(JobFileSpec(split_id=f"s{i}", source_path=p, page_count=1))
    with pytest.raises(JobError, match="batch too large"):
        create_job(files, root=tmp_path, job_id="too_big")
