"""MinerU job lifecycle (P3-T04).

Stages: planned -> submitted -> uploaded -> polling -> done | failed | timed_out

- Stable data_id per split (not accidental filenames)
- Manifest + events.jsonl under data/document-pipeline/jobs/<job_id>/
- Signed upload/download URLs are redacted; never persisted long-term
- Timeout is not failure: batch_id is kept so poll can resume
- Successful submit is not repeated on re-run (idempotent)
- Daily file/page budget counters recorded on successful submit
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen

from tools.document_pipeline.budget import (
    DEFAULT_BATCH_SPLIT_COUNT,
    BudgetSnapshot,
    fresh_budget,
)
from tools.document_pipeline.http_client import http_json, put_file, redact_url
from tools.document_pipeline.paths import DEFAULT_MINERU_BASE, PIPELINE_DATA_ROOT, ROOT
from tools.document_pipeline.raw import materialize_raw_from_zip

JOB_SCHEMA_VERSION = 1
TERMINAL_ITEM_STATES = frozenset({"done", "failed"})
ACTIVE_ITEM_STATES = frozenset(
    {"waiting", "pending", "running", "converting", "waiting-file", "queued"}
)

# Budget ledger lives next to jobs (local-only, gitignored under data/).
DEFAULT_BUDGET_LEDGER_REL = "data/document-pipeline/jobs/budget-ledger.v1.json"

JsonTransport = Callable[[str, str, dict[str, str], bytes | None, int], tuple[int, bytes]]
UploadFn = Callable[[str, Path], int]
DownloadFn = Callable[[str, Path], None]
ClockFn = Callable[[], float]
SleepFn = Callable[[float], None]


class JobError(ValueError):
    """Raised when a job cannot transition safely."""


class MinerUApi(Protocol):
    def apply_upload_urls(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def get_batch(self, batch_id: str) -> dict[str, Any]: ...

    def upload(self, upload_url: str, file_path: Path) -> int: ...

    def download(self, url: str, dest: Path) -> None: ...


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def jobs_root(*, root: Path | None = None) -> Path:
    base = root if root is not None else ROOT
    return base / "data" / "document-pipeline" / "jobs"


def job_path(job_id: str, *, root: Path | None = None) -> Path:
    if not _safe_job_id(job_id):
        raise JobError(f"invalid job_id: {job_id!r}")
    return jobs_root(root=root) / job_id


def _safe_job_id(job_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id))


def stable_data_id(split_id: str) -> str:
    """Stable MinerU data_id from split_id (alphanumeric + ._- only)."""
    raw = split_id.strip()
    if not raw:
        raise JobError("split_id must not be empty")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in raw)
    safe = re.sub(r"_+", "_", safe).strip("._-")
    if not safe:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        safe = f"split_{digest}"
    return safe[:128]


def relative_posix(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved.is_relative_to(root_resolved):
        return resolved.relative_to(root_resolved).as_posix()
    return resolved.name


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise JobError(f"missing json: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise JobError(f"expected object in {path}")
    return data


def redact_for_storage(value: Any) -> Any:
    """Recursively drop query strings from URL-like strings and known secret keys."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if key_l in {
                "file_urls",
                "upload_url",
                "full_zip_url",
                "url",
                "signed_url",
                "authorization",
            }:
                if isinstance(item, str):
                    out[key] = redact_url(item)
                elif isinstance(item, list):
                    out[key] = [
                        redact_url(x) if isinstance(x, str) else redact_for_storage(x) for x in item
                    ]
                else:
                    out[key] = redact_for_storage(item)
            else:
                out[key] = redact_for_storage(item)
        return out
    if isinstance(value, list):
        return [redact_for_storage(v) for v in value]
    if isinstance(value, str) and ("Signature=" in value or "Expires=" in value or "?" in value):
        if value.startswith("http://") or value.startswith("https://"):
            return redact_url(value)
    return value


def append_event(job_dir: Path, event: dict[str, Any]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "events.jsonl"
    row = {"at": utc_now_iso(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_events(job_dir: Path) -> list[dict[str, Any]]:
    path = job_dir / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def load_manifest(job_dir: Path) -> dict[str, Any]:
    return load_json(job_dir / "manifest.json")


def save_manifest(job_dir: Path, manifest: dict[str, Any]) -> None:
    # Never persist full signed URLs.
    write_json(job_dir / "manifest.json", redact_for_storage(manifest))


@dataclass(frozen=True)
class JobFileSpec:
    split_id: str
    source_path: Path
    page_count: int
    document_key: str | None = None
    document_version: str | None = None
    data_id: str | None = None

    def resolved_data_id(self) -> str:
        return self.data_id if self.data_id else stable_data_id(self.split_id)


def create_job(
    files: Sequence[JobFileSpec],
    *,
    root: Path | None = None,
    job_id: str | None = None,
    base_url: str = DEFAULT_MINERU_BASE,
    model_version: str = "vlm",
    language: str = "ch",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
    page_ranges: str | None = None,
) -> dict[str, Any]:
    """Create a planned job directory + manifest (no network)."""
    if not files:
        raise JobError("job requires at least one file")
    if len(files) > DEFAULT_BATCH_SPLIT_COUNT * 2:
        # Soft guard: design prefers 4–8; allow up to 12 for flexibility.
        raise JobError(
            f"batch too large ({len(files)} files); keep <= {DEFAULT_BATCH_SPLIT_COUNT * 2}"
        )

    base = root if root is not None else ROOT
    jid = job_id or f"job_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    if not _safe_job_id(jid):
        raise JobError(f"invalid job_id: {jid!r}")

    jdir = job_path(jid, root=base)
    if (jdir / "manifest.json").is_file():
        raise JobError(f"job already exists: {jid}")

    items: list[dict[str, Any]] = []
    page_total = 0
    for spec in files:
        if not spec.source_path.is_file():
            raise JobError(f"source file not found: {spec.source_path}")
        if spec.page_count < 1:
            raise JobError(f"page_count must be >= 1 for {spec.split_id}")
        size = spec.source_path.stat().st_size
        if size > 200 * 1024 * 1024:
            raise JobError(f"file exceeds 200MB: {spec.source_path.name} ({size} bytes)")
        data_id = spec.resolved_data_id()
        page_total += spec.page_count
        items.append(
            {
                "split_id": spec.split_id,
                "data_id": data_id,
                "source_relpath": relative_posix(spec.source_path, root=base),
                "source_file_name": spec.source_path.name,
                "source_size_bytes": size,
                "page_count": spec.page_count,
                "document_key": spec.document_key,
                "document_version": spec.document_version,
                "state": "planned",
                "upload_status": None,
                "err_msg": None,
                "extract_progress": None,
                "full_zip_url_redacted": None,
                "raw_relpath": None,
                "zip_sha256": None,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": jid,
        "stage": "planned",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "base_url": base_url.rstrip("/"),
        "batch_id": None,
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "is_ocr": is_ocr,
        "page_ranges": page_ranges,
        "file_count": len(items),
        "page_total": page_total,
        "budget": None,
        "items": items,
        "last_poll_at": None,
        "last_error": None,
        "timed_out": False,
        "downloaded": False,
    }
    jdir.mkdir(parents=True, exist_ok=True)
    save_manifest(jdir, manifest)
    append_event(
        jdir,
        {
            "type": "job_created",
            "stage": "planned",
            "file_count": len(items),
            "page_total": page_total,
        },
    )
    return manifest


@dataclass
class HttpMinerUClient:
    """Default MinerU client using injectable transport for tests."""

    base_url: str
    token: str
    timeout: int = 60
    transport: JsonTransport | None = None
    upload_fn: UploadFn | None = None
    download_fn: DownloadFn | None = None

    def apply_upload_urls(self, body: dict[str, Any]) -> dict[str, Any]:
        status, payload = http_json(
            "POST",
            f"{self.base_url.rstrip('/')}/api/v4/file-urls/batch",
            token=self.token,
            body=body,
            timeout=self.timeout,
            transport=self.transport,
        )
        if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            raise JobError(f"apply upload urls failed: status={status} body={payload}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise JobError(f"apply upload urls missing data: {payload}")
        return data

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        status, payload = http_json(
            "GET",
            f"{self.base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}",
            token=self.token,
            timeout=self.timeout,
            transport=self.transport,
        )
        if status != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            raise JobError(f"poll failed: status={status} body={payload}")
        return payload

    def upload(self, upload_url: str, file_path: Path) -> int:
        if self.upload_fn is not None:
            return self.upload_fn(upload_url, file_path)
        return put_file(upload_url, file_path, timeout=max(self.timeout, 300))

    def download(self, url: str, dest: Path) -> None:
        if self.download_fn is not None:
            self.download_fn(url, dest)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = Request(url, method="GET")
        with urlopen(req, timeout=max(self.timeout, 180)) as resp:
            dest.write_bytes(resp.read())


def load_budget_ledger(path: Path) -> BudgetSnapshot:
    if not path.is_file():
        return fresh_budget()
    data = load_json(path)
    return BudgetSnapshot(
        file_budget=int(data.get("file_budget", fresh_budget().file_budget)),
        page_budget=int(data.get("page_budget", fresh_budget().page_budget)),
        files_used=int(data.get("files_used", 0)),
        pages_used=int(data.get("pages_used", 0)),
    )


def save_budget_ledger(path: Path, snap: BudgetSnapshot) -> None:
    payload = {
        "schema_version": 1,
        "updated_at": utc_now_iso(),
        **snap.to_dict(),
    }
    write_json(path, payload)


def submit_job(
    job_dir: Path,
    client: MinerUApi,
    *,
    root: Path | None = None,
    budget_ledger_path: Path | None = None,
    reserve_budget: bool = True,
) -> dict[str, Any]:
    """Apply upload URLs, upload files, persist batch_id. Idempotent if already submitted."""
    base = root if root is not None else ROOT
    manifest = load_manifest(job_dir)
    stage = str(manifest.get("stage") or "planned")

    # Successful submit stages are idempotent. upload_failed may re-apply a new batch
    # (signed URLs are not retained). timed_out/done/failed keep batch_id for poll/download.
    if manifest.get("batch_id") and stage in {
        "submitted",
        "uploaded",
        "polling",
        "done",
        "failed",
        "timed_out",
    }:
        append_event(
            job_dir,
            {
                "type": "submit_skipped",
                "reason": "already_submitted",
                "batch_id": manifest.get("batch_id"),
                "stage": stage,
            },
        )
        return manifest

    if stage not in {"planned", "submit_failed", "upload_failed"}:
        raise JobError(f"cannot submit from stage={stage}")

    items = list(manifest["items"])
    file_specs = []
    paths: list[Path] = []
    for item in items:
        rel = item["source_relpath"]
        path = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        if not path.is_file():
            # Fall back: try original name under docs/ for local recovery
            raise JobError(f"source missing for submit: {rel}")
        paths.append(path)
        spec: dict[str, Any] = {
            "name": item["source_file_name"],
            "data_id": item["data_id"],
        }
        if manifest.get("is_ocr"):
            spec["is_ocr"] = True
        if manifest.get("page_ranges"):
            spec["page_ranges"] = manifest["page_ranges"]
        file_specs.append(spec)

    pages = int(manifest["page_total"])
    files_n = int(manifest["file_count"])
    ledger_path = (
        budget_ledger_path if budget_ledger_path is not None else base / DEFAULT_BUDGET_LEDGER_REL
    )
    if reserve_budget:
        snap = load_budget_ledger(ledger_path)
        if not snap.can_accept(files=files_n, pages=pages):
            raise JobError(
                f"budget exceeded: need files={files_n} pages={pages}, "
                f"remaining files={snap.files_remaining} pages={snap.pages_remaining}"
            )

    body = {
        "files": file_specs,
        "model_version": manifest["model_version"],
        "enable_formula": manifest["enable_formula"],
        "enable_table": manifest["enable_table"],
        "language": manifest["language"],
    }

    try:
        data = client.apply_upload_urls(body)
    except JobError as exc:
        manifest["stage"] = "submit_failed"
        manifest["last_error"] = str(exc)
        manifest["updated_at"] = utc_now_iso()
        save_manifest(job_dir, manifest)
        append_event(job_dir, {"type": "submit_failed", "error": str(exc)})
        raise

    batch_id = data.get("batch_id")
    urls = data.get("file_urls") or []
    if not batch_id or not isinstance(urls, list):
        raise JobError(f"apply response missing batch_id/file_urls: {redact_for_storage(data)}")
    if len(urls) != len(paths):
        raise JobError(f"url count mismatch: files={len(paths)} urls={len(urls)}")

    manifest["batch_id"] = str(batch_id)
    manifest["stage"] = "submitted"
    manifest["updated_at"] = utc_now_iso()
    manifest["last_error"] = None
    # Store redacted apply response (no signed URLs).
    manifest["apply_response"] = redact_for_storage({"batch_id": batch_id, "file_count": len(urls)})
    save_manifest(job_dir, manifest)
    append_event(
        job_dir,
        {"type": "submitted", "batch_id": batch_id, "file_count": len(urls)},
    )

    upload_ok = True
    for idx, (path, url, item) in enumerate(zip(paths, urls, items, strict=True)):
        if not isinstance(url, str) or not url:
            item["upload_status"] = "missing_url"
            upload_ok = False
            continue
        try:
            code = client.upload(url, path)
            item["upload_status"] = f"http_{code}"
            if code < 200 or code >= 300:
                upload_ok = False
                item["err_msg"] = f"upload http {code}"
            else:
                item["state"] = "waiting"
        except Exception as exc:  # noqa: BLE001 - record and continue
            upload_ok = False
            item["upload_status"] = "error"
            item["err_msg"] = str(exc)[:500]
        items[idx] = item

    manifest["items"] = items
    manifest["stage"] = "uploaded" if upload_ok else "upload_failed"
    manifest["updated_at"] = utc_now_iso()
    if not upload_ok:
        manifest["last_error"] = "one or more uploads failed"
    save_manifest(job_dir, manifest)
    append_event(
        job_dir,
        {
            "type": "uploaded" if upload_ok else "upload_failed",
            "batch_id": batch_id,
            "ok": upload_ok,
        },
    )

    if upload_ok and reserve_budget:
        snap = load_budget_ledger(ledger_path)
        reserved = snap.reserve(files=files_n, pages=pages)
        save_budget_ledger(ledger_path, reserved)
        manifest["budget"] = {
            "reserved_files": files_n,
            "reserved_pages": pages,
            "ledger_after": reserved.to_dict(),
        }
        manifest["updated_at"] = utc_now_iso()
        save_manifest(job_dir, manifest)
        append_event(
            job_dir,
            {
                "type": "budget_reserved",
                "files": files_n,
                "pages": pages,
                "files_used": reserved.files_used,
                "pages_used": reserved.pages_used,
            },
        )

    if not upload_ok:
        raise JobError("one or more uploads failed")
    return manifest


def _summarize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        progress = r.get("extract_progress")
        rows.append(
            {
                "data_id": r.get("data_id"),
                "file_name": r.get("file_name"),
                "state": r.get("state"),
                "err_msg": r.get("err_msg"),
                "extract_progress": progress if isinstance(progress, dict) else None,
                "full_zip_url_redacted": redact_url(r["full_zip_url"])
                if isinstance(r.get("full_zip_url"), str)
                else None,
            }
        )
    return rows


def _merge_poll_into_items(
    items: list[dict[str, Any]], results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_data: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("data_id"):
            by_data[str(r["data_id"])] = r
        if r.get("file_name"):
            by_name[str(r["file_name"])] = r

    updated: list[dict[str, Any]] = []
    for item in items:
        match = by_data.get(str(item.get("data_id"))) or by_name.get(
            str(item.get("source_file_name"))
        )
        row = dict(item)
        if match is not None:
            row["state"] = match.get("state") or row.get("state")
            row["err_msg"] = match.get("err_msg")
            progress = match.get("extract_progress")
            row["extract_progress"] = progress if isinstance(progress, dict) else None
            zip_url = match.get("full_zip_url")
            if isinstance(zip_url, str):
                row["full_zip_url_redacted"] = redact_url(zip_url)
                # Keep transient download URL only in memory via poll helper return;
                # store redacted form in manifest.
                row["_full_zip_url_transient"] = zip_url
        updated.append(row)
    return updated


def poll_job(
    job_dir: Path,
    client: MinerUApi,
    *,
    timeout_seconds: float = 1800,
    interval_seconds: float = 0.0,
    clock: ClockFn | None = None,
    sleep: SleepFn | None = None,
    max_rounds: int | None = None,
) -> dict[str, Any]:
    """Poll until terminal, timeout, or max_rounds.

    Timeout sets stage timed_out but keeps batch_id so a later poll can resume.
    """
    manifest = load_manifest(job_dir)
    batch_id = manifest.get("batch_id")
    if not batch_id:
        raise JobError("cannot poll without batch_id; submit first")

    now = clock if clock is not None else (lambda: __import__("time").time())
    sleeper = sleep if sleep is not None else (lambda s: __import__("time").sleep(s))
    deadline = now() + timeout_seconds
    last_signature: str | None = None
    rounds = 0
    last_payload: dict[str, Any] | None = None

    while True:
        rounds += 1
        payload = client.get_batch(str(batch_id))
        last_payload = payload
        results = (payload.get("data") or {}).get("extract_result") or []
        if not isinstance(results, list):
            results = []

        summary = _summarize_results(results)
        signature = json.dumps(
            [(s.get("data_id"), s.get("state"), s.get("extract_progress")) for s in summary],
            ensure_ascii=False,
            sort_keys=True,
        )
        items = _merge_poll_into_items(list(manifest["items"]), results)
        # Strip transient URLs before save.
        clean_items = []
        for item in items:
            row = {k: v for k, v in item.items() if k != "_full_zip_url_transient"}
            clean_items.append(row)
        manifest["items"] = clean_items
        manifest["last_poll_at"] = utc_now_iso()
        manifest["stage"] = "polling"
        manifest["updated_at"] = utc_now_iso()
        manifest["last_poll_summary"] = summary
        save_manifest(job_dir, manifest)

        if signature != last_signature:
            append_event(
                job_dir,
                {
                    "type": "poll_state",
                    "batch_id": batch_id,
                    "states": [s.get("state") for s in summary],
                    "summary": summary,
                },
            )
            last_signature = signature

        if results and all(
            isinstance(r, dict) and r.get("state") in TERMINAL_ITEM_STATES for r in results
        ):
            failed = any(r.get("state") == "failed" for r in results if isinstance(r, dict))
            manifest["stage"] = "failed" if failed else "done"
            manifest["timed_out"] = False
            manifest["updated_at"] = utc_now_iso()
            if failed:
                manifest["last_error"] = "one or more extract tasks failed"
            else:
                manifest["last_error"] = None
            save_manifest(job_dir, manifest)
            append_event(
                job_dir,
                {
                    "type": "poll_terminal",
                    "stage": manifest["stage"],
                    "batch_id": batch_id,
                    "states": [s.get("state") for s in summary],
                },
            )
            # Attach transient zip urls for download without writing them.
            return {
                "manifest": manifest,
                "payload": redact_for_storage(payload),
                "results": results,
                "timed_out": False,
            }

        if max_rounds is not None and rounds >= max_rounds:
            break
        if now() >= deadline:
            manifest["stage"] = "timed_out"
            manifest["timed_out"] = True
            manifest["updated_at"] = utc_now_iso()
            manifest["last_error"] = f"poll timed out after {timeout_seconds}s"
            save_manifest(job_dir, manifest)
            append_event(
                job_dir,
                {
                    "type": "poll_timeout",
                    "batch_id": batch_id,
                    "timeout_seconds": timeout_seconds,
                    "states": [s.get("state") for s in summary],
                },
            )
            return {
                "manifest": manifest,
                "payload": redact_for_storage(last_payload or {}),
                "results": results,
                "timed_out": True,
            }

        if interval_seconds > 0:
            sleeper(interval_seconds)
        else:
            # No sleep: still need a way to exit for tests without max_rounds.
            if max_rounds is None:
                # Single-shot poll when interval is 0 and no max_rounds.
                break

    return {
        "manifest": manifest,
        "payload": redact_for_storage(last_payload or {}),
        "results": results if last_payload else [],
        "timed_out": bool(manifest.get("timed_out")),
    }


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def download_job(
    job_dir: Path,
    client: MinerUApi,
    *,
    root: Path | None = None,
    results: list[dict[str, Any]] | None = None,
    enforce_safe_zip: bool = True,
) -> dict[str, Any]:
    """Download done items' full_zip_url into jobs/<id>/raw/<data_id>/.

    Idempotent: skips items that already have a zip with recorded sha256.
    """
    base = root if root is not None else ROOT
    manifest = load_manifest(job_dir)
    batch_id = manifest.get("batch_id")
    if not batch_id:
        raise JobError("cannot download without batch_id")

    if results is None:
        payload = client.get_batch(str(batch_id))
        results = (payload.get("data") or {}).get("extract_result") or []
        if not isinstance(results, list):
            results = []

    by_data: dict[str, dict[str, Any]] = {}
    for r in results:
        if isinstance(r, dict) and r.get("data_id"):
            by_data[str(r["data_id"])] = r

    items = list(manifest["items"])
    any_downloaded = False
    for idx, item in enumerate(items):
        data_id = str(item.get("data_id"))
        match = by_data.get(data_id)
        if match is None:
            continue
        state = match.get("state")
        item["state"] = state
        if state != "done":
            item["err_msg"] = match.get("err_msg")
            items[idx] = item
            continue

        raw_rel = item.get("raw_relpath")
        if raw_rel and item.get("zip_sha256"):
            raw_path = (
                base / raw_rel if not Path(str(raw_rel)).is_absolute() else Path(str(raw_rel))
            )
            zip_path = raw_path / "result.zip"
            if zip_path.is_file():
                append_event(
                    job_dir,
                    {
                        "type": "download_skipped",
                        "data_id": data_id,
                        "reason": "already_downloaded",
                    },
                )
                continue

        zip_url = match.get("full_zip_url")
        if not isinstance(zip_url, str) or not zip_url:
            item["err_msg"] = "missing full_zip_url"
            items[idx] = item
            continue

        raw_dir = job_dir / "raw" / data_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        zip_path = raw_dir / "result.zip"
        # Download to a temp name first, then materialize (verify + unpack + manifest).
        tmp_zip = raw_dir / "result.zip.partial"
        client.download(zip_url, tmp_zip)
        try:
            raw_meta = materialize_raw_from_zip(
                tmp_zip,
                raw_dir,
                require_markdown=True,
                copy_zip=True,
            )
        except Exception as exc:  # noqa: BLE001 - record and continue other items
            tmp_zip.unlink(missing_ok=True)
            item["err_msg"] = f"raw materialize failed: {exc}"[:500]
            items[idx] = item
            append_event(
                job_dir,
                {"type": "download_failed", "data_id": data_id, "error": str(exc)[:300]},
            )
            continue
        finally:
            tmp_zip.unlink(missing_ok=True)
        zip_hash = str(raw_meta.get("zip_sha256") or sha256_file(zip_path))
        item["raw_relpath"] = relative_posix(raw_dir, root=base)
        item["zip_sha256"] = zip_hash
        item["full_zip_url_redacted"] = redact_url(zip_url)
        item["err_msg"] = None
        item["raw_entry_check"] = raw_meta.get("entry_check")
        items[idx] = item
        any_downloaded = True
        append_event(
            job_dir,
            {
                "type": "downloaded",
                "data_id": data_id,
                "zip_sha256": zip_hash,
                "raw_relpath": item["raw_relpath"],
                "output_hashes": raw_meta.get("output_hashes"),
            },
        )

    manifest["items"] = items
    all_done = all(i.get("state") == "done" and i.get("zip_sha256") for i in items)
    any_failed = any(i.get("state") == "failed" for i in items)
    if all_done:
        manifest["stage"] = "done"
        manifest["downloaded"] = True
        manifest["last_error"] = None
    elif any_failed and all(i.get("state") in TERMINAL_ITEM_STATES for i in items):
        manifest["stage"] = "failed"
        manifest["downloaded"] = any_downloaded or bool(manifest.get("downloaded"))
        manifest["last_error"] = "one or more extract tasks failed"
    else:
        manifest["downloaded"] = any_downloaded or bool(manifest.get("downloaded"))
    manifest["updated_at"] = utc_now_iso()
    save_manifest(job_dir, manifest)
    append_event(
        job_dir,
        {
            "type": "download_finished",
            "stage": manifest["stage"],
            "downloaded": manifest["downloaded"],
        },
    )
    return manifest


def create_job_from_split_manifest(
    split_manifest: dict[str, Any],
    *,
    root: Path | None = None,
    job_id: str | None = None,
    limit: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a job from a DOC-002 split-manifest (uses output_relpath PDFs)."""
    base = root if root is not None else ROOT
    splits = list(split_manifest.get("splits") or [])
    if limit is not None:
        splits = splits[:limit]
    files: list[JobFileSpec] = []
    for s in splits:
        if not isinstance(s, dict):
            continue
        rel = s.get("output_relpath")
        if not isinstance(rel, str):
            raise JobError(f"split missing output_relpath: {s.get('split_id')}")
        path = base / rel
        files.append(
            JobFileSpec(
                split_id=str(s["split_id"]),
                source_path=path,
                page_count=int(s.get("page_count") or 0),
                document_key=str(split_manifest.get("document_key") or ""),
                document_version=str(split_manifest.get("document_version") or ""),
            )
        )
    return create_job(files, root=base, job_id=job_id, **kwargs)


__all__ = [
    "DEFAULT_BATCH_SPLIT_COUNT",
    "DEFAULT_BUDGET_LEDGER_REL",
    "JOB_SCHEMA_VERSION",
    "HttpMinerUClient",
    "JobError",
    "JobFileSpec",
    "PIPELINE_DATA_ROOT",
    "append_event",
    "create_job",
    "create_job_from_split_manifest",
    "download_job",
    "job_path",
    "jobs_root",
    "load_events",
    "load_manifest",
    "poll_job",
    "redact_for_storage",
    "save_manifest",
    "stable_data_id",
    "submit_job",
]
