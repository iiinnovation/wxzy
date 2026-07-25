"""Versioned publication exporter (P5-T08).

Package layout:
  publication/
    manifest.json
    documents.json
    chapters.json
    chunks.jsonl
    cards.jsonl
    card_sources.jsonl
    checksums.json
    quality-summary.json

Rules:
  - only approved cards export
  - every exported card must have source citations (sources/chunk_ids)
  - critical approved cards require reviewer + reviewed_at
  - no local absolute paths, secrets, or full textbook body
  - file hashes in checksums.json are recomputable
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.candidate_schema import (
    CandidateCardV2,
    CandidateStatus,
    RiskLevel,
    validate_candidate_card_v2,
)

STAGE = "publication_export"
STAGE_VERSION = "p5t08-v1"
PUBLICATION_SCHEMA_VERSION = 1

ABS_PATH_RE = re.compile(r"(^|[\s\"'])/(Users|home|var|tmp|private|etc)/")
SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|openid)", re.I)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_card(card: CandidateCardV2 | dict[str, Any]) -> CandidateCardV2:
    return card if isinstance(card, CandidateCardV2) else validate_candidate_card_v2(card)


def _status(card: CandidateCardV2) -> CandidateStatus:
    return card.status if isinstance(card.status, CandidateStatus) else CandidateStatus(str(card.status))


def _risk(card: CandidateCardV2) -> RiskLevel:
    return card.risk_level if isinstance(card.risk_level, RiskLevel) else RiskLevel(str(card.risk_level))


def _contains_abs_path(value: Any) -> bool:
    if isinstance(value, str):
        if value.startswith("/") and not value.startswith("//"):
            # allow pure relative-looking fragments; flag absolute OS paths
            if ABS_PATH_RE.search(" " + value) or value.startswith(("/Users/", "/home/", "/var/", "/tmp/", "/private/")):
                return True
        return bool(ABS_PATH_RE.search(value))
    if isinstance(value, dict):
        return any(_contains_abs_path(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_abs_path(v) for v in value)
    return False


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for k, v in value.items():
            if SECRET_KEY_RE.search(str(k)):
                return True
            if _contains_secret_key(v):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret_key(v) for v in value)
    return False


@dataclass
class PublicationExportError(ValueError):
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return "; ".join(self.errors) if self.errors else "publication export failed"


@dataclass
class PublicationPackage:
    publication_id: str
    out_dir: Path
    manifest: dict[str, Any]
    checksums: dict[str, Any]
    card_count: int
    document_count: int
    chapter_count: int
    chunk_count: int
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "out_dir": str(self.out_dir),
            "card_count": self.card_count,
            "document_count": self.document_count,
            "chapter_count": self.chapter_count,
            "chunk_count": self.chunk_count,
            "source_count": self.source_count,
            "manifest_hash": self.manifest.get("manifest_hash"),
            "status": "publication_package",
        }


def assert_card_exportable(card: CandidateCardV2) -> list[str]:
    errors: list[str] = []
    # ensure schema/gate
    try:
        validate_candidate_card_v2(card)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{card.id}: schema/gate failed: {exc}")
        return errors

    if _status(card) != CandidateStatus.APPROVED:
        errors.append(f"{card.id}: not approved (status={_status(card).value})")

    has_sources = bool(card.sources)
    has_chunks = bool(card.chunk_ids)
    if not has_sources and not has_chunks:
        errors.append(f"{card.id}: missing source citations")
    if has_sources:
        for src in card.sources:
            if not (src.excerpt or "").strip():
                errors.append(f"{card.id}: empty source excerpt")
            if not (src.chunk_id or "").strip():
                errors.append(f"{card.id}: source missing chunk_id")
    if not (card.source_excerpt or "").strip():
        errors.append(f"{card.id}: missing source_excerpt")

    if _risk(card) == RiskLevel.CRITICAL:
        if not card.reviewer or not card.reviewed_at:
            errors.append(f"{card.id}: critical approved card requires reviewer/reviewed_at")

    # forbidden payload content
    payload = card.model_dump(mode="json")
    if _contains_abs_path(payload):
        errors.append(f"{card.id}: contains absolute local path")
    if _contains_secret_key(payload):
        errors.append(f"{card.id}: contains secret-like field")
    return errors


def _card_to_publication_record(card: CandidateCardV2) -> dict[str, Any]:
    return {
        "id": card.id,
        "document_key": card.document_key,
        "document_version": card.document_version,
        "book": card.book,
        "chapter": card.chapter,
        "section": card.section,
        "card_type": card.card_type,
        "question": card.question,
        "answer": card.answer,
        "answer_points": list(card.answer_points or []),
        "tags": list(card.tags or []),
        "risk_level": _risk(card).value,
        "risk_flags": list(card.risk_flags or []),
        "content_hash": card.content_hash,
        "status": CandidateStatus.APPROVED.value,
        "generator": card.generator,
        "model": card.model,
        "prompt_version": card.prompt_version,
        "generation_batch_id": card.generation_batch_id,
        "input_hash": card.input_hash,
        "reviewer": card.reviewer,
        "reviewed_at": card.reviewed_at,
        "review_notes": card.review_notes,
        "review_decision": None
        if card.review_decision is None
        else (
            card.review_decision.value
            if hasattr(card.review_decision, "value")
            else str(card.review_decision)
        ),
        "chunk_ids": list(card.chunk_ids or []),
        "pdf_page_indexes": list(card.pdf_page_indexes or []),
        "printed_page_labels": list(card.printed_page_labels or []),
        # keep short source_excerpt for catalog display; full textbook body never included
        "source_excerpt": card.source_excerpt,
    }


def _sources_for_card(card: CandidateCardV2) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if card.sources:
        for src in card.sources:
            rows.append(
                {
                    "card_id": card.id,
                    "citation_order": src.citation_order,
                    "chunk_id": src.chunk_id,
                    "excerpt": src.excerpt,
                    "pdf_page_index_start": src.pdf_page_index_start,
                    "pdf_page_index_end": src.pdf_page_index_end,
                    "printed_page_start_label": src.printed_page_start_label,
                    "printed_page_end_label": src.printed_page_end_label,
                }
            )
        return rows
    # synthesize minimal citation rows from chunk_ids + source_excerpt when sources absent
    for idx, chunk_id in enumerate(card.chunk_ids or []):
        page = card.pdf_page_indexes[0] if card.pdf_page_indexes else 0
        label = card.printed_page_labels[0] if card.printed_page_labels else None
        rows.append(
            {
                "card_id": card.id,
                "citation_order": idx,
                "chunk_id": chunk_id,
                "excerpt": card.source_excerpt,
                "pdf_page_index_start": page,
                "pdf_page_index_end": page,
                "printed_page_start_label": label,
                "printed_page_end_label": label,
            }
        )
    return rows


def _derive_documents(cards: Sequence[CandidateCardV2], documents: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if documents:
        cleaned: list[dict[str, Any]] = []
        for doc in documents:
            item = {
                k: v
                for k, v in dict(doc).items()
                if k not in {"source_abs_path", "absolute_path", "path", "local_path"}
                and not (isinstance(v, str) and v.startswith(("/Users/", "/home/", "/var/", "/tmp/", "/private/")))
            }
            if _contains_secret_key(item) or _contains_abs_path(item):
                raise PublicationExportError([f"document payload contains forbidden fields: {item.get('document_key')}"])
            cleaned.append(item)
        return cleaned
    # derive minimal docs from cards
    by_key: dict[str, dict[str, Any]] = {}
    for card in cards:
        by_key.setdefault(
            card.document_key,
            {
                "document_key": card.document_key,
                "document_version": card.document_version,
                "title": card.book,
            },
        )
    return list(by_key.values())


def _derive_chapters(cards: Sequence[CandidateCardV2], chapters: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if chapters:
        return [dict(c) for c in chapters]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for card in cards:
        chapter = card.chapter or "未分章"
        key = (card.document_key, chapter)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "document_key": card.document_key,
                "document_version": card.document_version,
                "chapter": chapter,
                "section": card.section,
            }
        )
    return out


def _derive_chunks(cards: Sequence[CandidateCardV2], chunks: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if chunks:
        cleaned = []
        for ch in chunks:
            item = dict(ch)
            # never ship huge fulltext if present
            if "text" in item and isinstance(item["text"], str) and len(item["text"]) > 2000:
                item["text"] = item["text"][:2000]
            if "cleaned_text" in item and isinstance(item["cleaned_text"], str) and len(item["cleaned_text"]) > 2000:
                item["cleaned_text"] = item["cleaned_text"][:2000]
            cleaned.append(item)
        return cleaned
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        for src in card.sources or []:
            if src.chunk_id in seen:
                continue
            seen.add(src.chunk_id)
            out.append(
                {
                    "id": src.chunk_id,
                    "document_key": card.document_key,
                    "document_version": card.document_version,
                    "excerpt": src.excerpt[:500],
                    "pdf_page_index_start": src.pdf_page_index_start,
                    "pdf_page_index_end": src.pdf_page_index_end,
                }
            )
        for cid in card.chunk_ids or []:
            if cid in seen:
                continue
            seen.add(cid)
            out.append(
                {
                    "id": cid,
                    "document_key": card.document_key,
                    "document_version": card.document_version,
                    "excerpt": (card.source_excerpt or "")[:500],
                }
            )
    return out


def _quality_summary(cards: Sequence[CandidateCardV2], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    risk_dist: dict[str, int] = {}
    type_dist: dict[str, int] = {}
    for card in cards:
        rl = _risk(card).value
        risk_dist[rl] = risk_dist.get(rl, 0) + 1
        type_dist[card.card_type] = type_dist.get(card.card_type, 0) + 1
    payload = {
        "exported_card_count": len(cards),
        "risk_distribution": risk_dist,
        "card_type_distribution": type_dist,
        "approved_only": True,
        "notes": "quality-summary is package-local and excludes full textbook text",
    }
    if extra:
        payload.update(extra)
    return payload


def _write_json(path: Path, payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> str:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)


def recompute_checksums(package_dir: Path) -> dict[str, str]:
    """Recompute sha256 for package files (excluding checksums/manifest hash circularity)."""
    files = [
        "documents.json",
        "chapters.json",
        "chunks.jsonl",
        "cards.jsonl",
        "card_sources.jsonl",
        "quality-summary.json",
    ]
    out: dict[str, str] = {}
    for name in files:
        path = package_dir / name
        out[name] = sha256_bytes(path.read_bytes())
    return out


def export_publication(
    cards: Sequence[CandidateCardV2 | dict[str, Any]],
    *,
    out_dir: Path,
    publication_id: str | None = None,
    documents: Sequence[dict[str, Any]] | None = None,
    chapters: Sequence[dict[str, Any]] | None = None,
    chunks: Sequence[dict[str, Any]] | None = None,
    pipeline_version: str = "p5",
    generation_version: str = "p5t05-v1",
    review_version: str = "p5t07-v1",
    quality_extra: dict[str, Any] | None = None,
) -> PublicationPackage:
    """Export an approved-only publication package."""
    models: list[CandidateCardV2] = []
    errors: list[str] = []
    for raw in cards:
        try:
            card = _as_card(raw)
        except Exception as exc:  # noqa: BLE001 - collect and surface as export errors
            cid = getattr(raw, "id", None) or (raw.get("id") if isinstance(raw, dict) else "unknown")
            errors.append(f"{cid}: schema/gate failed: {exc}")
            continue
        models.append(card)
        errors.extend(assert_card_exportable(card))
    if not models and not errors:
        errors.append("no cards to export")
    if not models and errors:
        raise PublicationExportError(errors)
    if errors:
        raise PublicationExportError(errors)

    pub_id = publication_id or f"pub-{uuid.uuid4().hex[:12]}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_rows = _derive_documents(models, documents)
    chapter_rows = _derive_chapters(models, chapters)
    chunk_rows = _derive_chunks(models, chunks)
    card_rows = [_card_to_publication_record(c) for c in models]
    source_rows: list[dict[str, Any]] = []
    for card in models:
        source_rows.extend(_sources_for_card(card))
    quality = _quality_summary(models, extra=quality_extra)

    checksums = {
        "documents.json": _write_json(out_dir / "documents.json", doc_rows),
        "chapters.json": _write_json(out_dir / "chapters.json", chapter_rows),
        "chunks.jsonl": _write_jsonl(out_dir / "chunks.jsonl", chunk_rows),
        "cards.jsonl": _write_jsonl(out_dir / "cards.jsonl", card_rows),
        "card_sources.jsonl": _write_jsonl(out_dir / "card_sources.jsonl", source_rows),
        "quality-summary.json": _write_json(out_dir / "quality-summary.json", quality),
    }

    # package content hash over stable file hashes
    package_hash = sha256_text(canonical_json(checksums))
    manifest = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "publication_id": pub_id,
        "stage": STAGE,
        "stage_version": STAGE_VERSION,
        "pipeline_version": pipeline_version,
        "generation_version": generation_version,
        "review_version": review_version,
        "document_versions": sorted({c.document_version for c in models}),
        "counts": {
            "documents": len(doc_rows),
            "chapters": len(chapter_rows),
            "chunks": len(chunk_rows),
            "cards": len(card_rows),
            "card_sources": len(source_rows),
        },
        "checksums": checksums,
        "package_hash": package_hash,
        "created_at": now_iso(),
        "status": "ready_for_import",
    }
    # manifest hash excludes its own hash field
    manifest_hash = sha256_text(canonical_json(manifest))
    manifest["manifest_hash"] = manifest_hash

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksum_payload = {
        "schema_version": 1,
        "publication_id": pub_id,
        "files": checksums,
        "package_hash": package_hash,
        "manifest_hash": manifest_hash,
        "algorithm": "sha256",
    }
    (out_dir / "checksums.json").write_text(
        json.dumps(checksum_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return PublicationPackage(
        publication_id=pub_id,
        out_dir=out_dir,
        manifest=manifest,
        checksums=checksum_payload,
        card_count=len(card_rows),
        document_count=len(doc_rows),
        chapter_count=len(chapter_rows),
        chunk_count=len(chunk_rows),
        source_count=len(source_rows),
    )


def verify_package_checksums(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    recorded = json.loads((package_dir / "checksums.json").read_text(encoding="utf-8"))
    actual = recompute_checksums(package_dir)
    mismatches = {
        name: {"recorded": recorded["files"].get(name), "actual": digest}
        for name, digest in actual.items()
        if recorded.get("files", {}).get(name) != digest
    }
    package_hash = sha256_text(canonical_json(actual))
    return {
        "ok": not mismatches and package_hash == recorded.get("package_hash"),
        "mismatches": mismatches,
        "package_hash_recorded": recorded.get("package_hash"),
        "package_hash_actual": package_hash,
    }


__all__ = [
    "PUBLICATION_SCHEMA_VERSION",
    "STAGE",
    "STAGE_VERSION",
    "PublicationExportError",
    "PublicationPackage",
    "assert_card_exportable",
    "export_publication",
    "recompute_checksums",
    "verify_package_checksums",
]
