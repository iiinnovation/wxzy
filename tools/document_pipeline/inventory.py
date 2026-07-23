"""Document inventory (DOC-001).

Scans local PDF sources, records fingerprint/page/size metadata, and writes a
stable inventory document. Absolute paths may appear only in a local runtime
manifest; publication payloads never include them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.paths import (
    DOCUMENT_KEYS,
    DOCUMENT_PAGE_COUNTS,
    PIPELINE_DATA_ROOT,
    ROOT,
)

INVENTORY_SCHEMA_VERSION = 1
DEFAULT_COPYRIGHT_SCOPE = "personal-use"
DEFAULT_SOURCE_DIR_REL = "docs"
DEFAULT_INVENTORY_REL = "data/document-pipeline/inventory/documents.v1.json"
DEFAULT_LOCAL_MANIFEST_REL = "data/document-pipeline/inventory/local_sources.v1.json"

PageCounter = Callable[[Path], int]


class InventoryError(ValueError):
    """Raised when the source corpus cannot be inventoried safely."""


def inventory_dir(*, root: Path | None = None) -> Path:
    base = root if root is not None else ROOT
    return base / "data" / "document-pipeline" / "inventory"


def default_inventory_path(*, root: Path | None = None) -> Path:
    return inventory_dir(root=root) / "documents.v1.json"


def default_local_manifest_path(*, root: Path | None = None) -> Path:
    return inventory_dir(root=root) / "local_sources.v1.json"


def title_from_source_file_name(file_name: str) -> str:
    stem = Path(file_name).stem
    stem = re.sub(r"\(\d+\)$", "", stem).strip()
    return stem


def relative_posix(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved.is_relative_to(root_resolved):
        return resolved.relative_to(root_resolved).as_posix()
    # Outside-root paths are never publication-safe; callers must not embed them.
    return resolved.name


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def count_pdf_pages(path: Path) -> int:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise InventoryError(
            "PyMuPDF (fitz) is required for page counts: pip install 'pymupdf>=1.25,<2.0'"
        ) from exc
    doc = fitz.open(path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def document_key_for_file_name(file_name: str) -> str | None:
    for key, known_name in DOCUMENT_KEYS.items():
        if known_name == file_name:
            return key
    return None


def list_source_pdfs(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise InventoryError(f"source directory not found: {source_dir}")
    return sorted(path for path in source_dir.glob("*.pdf") if path.is_file())


def build_document_record(
    *,
    document_key: str,
    source_path: Path,
    root: Path,
    page_counter: PageCounter | None = None,
    copyright_scope: str = DEFAULT_COPYRIGHT_SCOPE,
    registered_at: str | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not source_path.is_file():
        raise InventoryError(f"source PDF not found: {source_path}")
    file_name = source_path.name
    if Path(file_name).name != file_name or "/" in file_name or "\\" in file_name:
        raise InventoryError(f"source file name must not contain path separators: {file_name!r}")

    size_bytes = source_path.stat().st_size
    source_sha256 = sha256_file(source_path)
    counter = page_counter or count_pdf_pages
    page_count = counter(source_path)
    if page_count <= 0:
        raise InventoryError(f"PDF has no pages: {file_name}")

    version = 1
    registered = registered_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    if previous is not None:
        prev_sha = previous.get("source_sha256")
        prev_pages = previous.get("page_count")
        prev_size = previous.get("size_bytes")
        if (
            prev_sha == source_sha256
            and prev_pages == page_count
            and prev_size == size_bytes
            and previous.get("source_file_name") == file_name
        ):
            # Identical content: keep version and original registration time.
            version = int(previous.get("version") or 1)
            registered = str(previous.get("registered_at") or registered)
        else:
            version = int(previous.get("version") or 1) + 1

    record: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "document_key": document_key,
        "title": title_from_source_file_name(file_name),
        "source_file_name": file_name,
        "source_relpath": relative_posix(source_path, root=root),
        "source_sha256": source_sha256,
        "page_count": page_count,
        "size_bytes": size_bytes,
        "copyright_scope": copyright_scope,
        "version": version,
        "document_version": f"{document_key}.v{version}.{source_sha256[:12]}",
        "registered_at": registered,
    }
    planned = DOCUMENT_PAGE_COUNTS.get(document_key)
    if planned is not None:
        record["planned_page_count"] = planned
        record["page_count_matches_plan"] = page_count == planned
    return record


def _index_previous(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in documents:
        key = item.get("document_key")
        if isinstance(key, str) and key:
            indexed[key] = item
    return indexed


def load_inventory(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise InventoryError(f"inventory root must be an object: {path}")
    return raw


def scan_inventory(
    *,
    root: Path | None = None,
    source_dir: Path | None = None,
    page_counter: PageCounter | None = None,
    copyright_scope: str = DEFAULT_COPYRIGHT_SCOPE,
    previous_inventory: dict[str, Any] | None = None,
    registered_at: str | None = None,
    require_expected_keys: bool = True,
) -> dict[str, Any]:
    """Scan PDFs and return a publication-safe inventory document."""
    base = root if root is not None else ROOT
    sources = source_dir if source_dir is not None else base / DEFAULT_SOURCE_DIR_REL
    pdfs = list_source_pdfs(sources)

    prev_docs = []
    if previous_inventory is not None:
        docs = previous_inventory.get("documents")
        if isinstance(docs, list):
            prev_docs = [d for d in docs if isinstance(d, dict)]
    previous_by_key = _index_previous(prev_docs)

    documents: list[dict[str, Any]] = []
    unknown: list[str] = []
    seen_keys: set[str] = set()

    for pdf in pdfs:
        key = document_key_for_file_name(pdf.name)
        if key is None:
            unknown.append(pdf.name)
            continue
        if key in seen_keys:
            raise InventoryError(f"duplicate document_key from file names: {key}")
        seen_keys.add(key)
        documents.append(
            build_document_record(
                document_key=key,
                source_path=pdf,
                root=base,
                page_counter=page_counter,
                copyright_scope=copyright_scope,
                registered_at=registered_at,
                previous=previous_by_key.get(key),
            )
        )

    # Stable order: canonical DOCUMENT_KEYS order, then any extras.
    order = {key: idx for idx, key in enumerate(DOCUMENT_KEYS)}
    documents.sort(key=lambda d: (order.get(str(d["document_key"]), 10_000), d["document_key"]))

    missing = [key for key in DOCUMENT_KEYS if key not in seen_keys]
    if require_expected_keys and missing:
        raise InventoryError("missing expected corpus PDFs for keys: " + ", ".join(missing))
    if unknown and require_expected_keys:
        raise InventoryError(
            "unmapped PDF file name(s); add document_key mapping: " + ", ".join(unknown)
        )

    page_total = sum(int(d["page_count"]) for d in documents)
    generated_at = registered_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    # If every document kept its previous registered_at and the set is identical,
    # keep the previous generated_at for full output stability.
    if previous_inventory is not None and documents:
        prev_list = previous_inventory.get("documents") or []
        if isinstance(prev_list, list) and len(prev_list) == len(documents):
            same = True
            prev_by = _index_previous([d for d in prev_list if isinstance(d, dict)])
            for doc in documents:
                prev = prev_by.get(str(doc["document_key"]))
                if prev is None:
                    same = False
                    break
                for field in (
                    "source_sha256",
                    "page_count",
                    "size_bytes",
                    "source_file_name",
                    "version",
                    "registered_at",
                ):
                    if prev.get(field) != doc.get(field):
                        same = False
                        break
                if not same:
                    break
            if same and previous_inventory.get("generated_at"):
                generated_at = str(previous_inventory["generated_at"])

    inventory: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_dir": DEFAULT_SOURCE_DIR_REL
        if source_dir is None
        else relative_posix(sources, root=base),
        "document_count": len(documents),
        "page_total": page_total,
        "documents": documents,
    }
    if missing:
        inventory["missing_document_keys"] = missing
    if unknown:
        inventory["unmapped_source_files"] = unknown
    return inventory


def build_local_manifest(
    inventory: dict[str, Any],
    *,
    root: Path | None = None,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Local-only mapping that may include absolute paths; never publish this."""
    base = root if root is not None else ROOT
    sources = source_dir if source_dir is not None else base / DEFAULT_SOURCE_DIR_REL
    entries = []
    for doc in inventory.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        name = doc.get("source_file_name")
        if not isinstance(name, str):
            continue
        path = sources / name
        entries.append(
            {
                "document_key": doc.get("document_key"),
                "source_file_name": name,
                "source_abs_path": str(path.resolve()) if path.exists() else None,
                "source_relpath": doc.get("source_relpath"),
                "source_sha256": doc.get("source_sha256"),
                "document_version": doc.get("document_version"),
            }
        )
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "note": "LOCAL ONLY — absolute paths must not enter publications or APIs",
        "root": str(base.resolve()),
        "source_dir": str(sources.resolve()),
        "generated_at": inventory.get("generated_at"),
        "sources": entries,
    }


def publication_view(inventory: dict[str, Any]) -> dict[str, Any]:
    """Strip any accidental absolute-path fields before publication packaging."""
    docs = []
    for doc in inventory.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        clean = {
            key: value
            for key, value in doc.items()
            if key
            not in {
                "source_abs_path",
                "absolute_path",
                "path",
                "local_path",
            }
            and not (isinstance(value, str) and value.startswith("/"))
        }
        # source_relpath is repo-relative and publication-adjacent; keep it.
        docs.append(clean)
    return {
        "schema_version": inventory.get("schema_version", INVENTORY_SCHEMA_VERSION),
        "generated_at": inventory.get("generated_at"),
        "source_dir": inventory.get("source_dir"),
        "document_count": inventory.get("document_count"),
        "page_total": inventory.get("page_total"),
        "documents": docs,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_inventory(
    *,
    root: Path | None = None,
    source_dir: Path | None = None,
    out_path: Path | None = None,
    local_manifest_path: Path | None = None,
    page_counter: PageCounter | None = None,
    copyright_scope: str = DEFAULT_COPYRIGHT_SCOPE,
    write_local_manifest: bool = True,
    require_expected_keys: bool = True,
) -> dict[str, Any]:
    base = root if root is not None else ROOT
    inventory_path = out_path if out_path is not None else default_inventory_path(root=base)
    previous = load_inventory(inventory_path)
    inventory = scan_inventory(
        root=base,
        source_dir=source_dir,
        page_counter=page_counter,
        copyright_scope=copyright_scope,
        previous_inventory=previous,
        require_expected_keys=require_expected_keys,
    )
    write_json(inventory_path, inventory)
    result: dict[str, Any] = {
        "inventory_path": str(inventory_path.relative_to(base))
        if inventory_path.is_relative_to(base)
        else str(inventory_path),
        "document_count": inventory["document_count"],
        "page_total": inventory["page_total"],
        "documents": [
            {
                "document_key": d["document_key"],
                "page_count": d["page_count"],
                "version": d["version"],
                "source_sha256": d["source_sha256"],
            }
            for d in inventory["documents"]
        ],
    }
    if write_local_manifest:
        local_path = (
            local_manifest_path
            if local_manifest_path is not None
            else default_local_manifest_path(root=base)
        )
        local = build_local_manifest(inventory, root=base, source_dir=source_dir)
        write_json(local_path, local)
        result["local_manifest_path"] = (
            str(local_path.relative_to(base))
            if local_path.is_relative_to(base)
            else str(local_path)
        )
    return result


# Keep scaffolding helpers used by P3-T01 tests.
def planned_document_keys() -> list[str]:
    return list(DOCUMENT_KEYS.keys())


def planned_corpus_summary() -> dict[str, Any]:
    from tools.document_pipeline.paths import CORPUS_PAGE_TOTAL

    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "document_count": len(DOCUMENT_KEYS),
        "page_total": CORPUS_PAGE_TOTAL,
        "documents": [
            {
                "document_key": key,
                "source_file_name": DOCUMENT_KEYS[key],
                "planned_page_count": DOCUMENT_PAGE_COUNTS[key],
            }
            for key in DOCUMENT_KEYS
        ],
    }


__all__ = [
    "DEFAULT_COPYRIGHT_SCOPE",
    "INVENTORY_SCHEMA_VERSION",
    "InventoryError",
    "PIPELINE_DATA_ROOT",
    "build_document_record",
    "build_local_manifest",
    "count_pdf_pages",
    "default_inventory_path",
    "default_local_manifest_path",
    "document_key_for_file_name",
    "list_source_pdfs",
    "load_inventory",
    "planned_corpus_summary",
    "planned_document_keys",
    "publication_view",
    "run_inventory",
    "scan_inventory",
    "sha256_file",
    "title_from_source_file_name",
    "write_json",
]
