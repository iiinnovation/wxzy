"""Candidate Card v2 schema, gate, and v1 converter (P5-T01).

Tracked schema:
  tools/document_pipeline/schemas/candidate_card.v2.schema.json

Acceptance:
  - existing offline v1 sample cards convert to v2
  - gate fails when provenance is missing or high/critical risk lacks flags
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from tools.document_pipeline.paths import ROOT

CANDIDATE_SCHEMA_VERSION = 2
CANDIDATE_CARD_V2_SCHEMA_PATH = (
    ROOT / "tools" / "document_pipeline" / "schemas" / "candidate_card.v2.schema.json"
)
CANDIDATE_CARD_V1_SCHEMA_PATH = (
    ROOT / "tools" / "document_pipeline" / "schemas" / "candidate_card.v1.schema.json"
)

# Keep the historical sample path pointer for local CLI compatibility.
LEGACY_CANDIDATE_SCHEMA_PATH = ROOT / "data" / "mineru" / "cards" / "candidate_card.schema.json"

BOOK_TO_DOCUMENT_KEY: dict[str, str] = {
    "方剂学": "fangji",
    "中医内科学": "neike",
    "中医基础理论": "jichu",
    "中医诊断学": "zhenduan",
    "中药学": "zhongyao",
    "针灸学": "zhenjiu",
    "人文": "renwen",
}

# Default document_version placeholders used only when converting legacy samples
# that predate inventory registration. Real pipeline cards must pass explicit
# document_version from inventory/jobs.
LEGACY_DOCUMENT_VERSION: dict[str, str] = {
    "fangji": "fangji.v1.legacy-sample",
    "neike": "neike.v1.legacy-sample",
    "jichu": "jichu.v1.legacy-sample",
    "zhenduan": "zhenduan.v1.legacy-sample",
    "zhongyao": "zhongyao.v1.legacy-sample",
    "zhenjiu": "zhenjiu.v1.legacy-sample",
    "renwen": "renwen.v1.legacy-sample",
}

# Risk defaults by card type for conversion. Later template tasks can refine.
CARD_TYPE_DEFAULT_RISK: dict[str, tuple[str, list[str]]] = {
    "formula_compose": ("high", ["dosage_or_compose"]),
    "formula_function": ("medium", ["formula_function"]),
    "formula_indication": ("medium", ["formula_indication"]),
    "formula_song": ("high", ["formula_song"]),
    "formula_usage_note": ("high", ["usage_or_caution"]),
    "disease_concept": ("low", []),
    "disease_pathogenesis": ("medium", ["pathogenesis_summary"]),
    "syndrome_formula": ("high", ["syndrome_formula"]),
    "treatment_principle": ("medium", ["treatment_principle"]),
    "versioned_classification": ("critical", ["multi_version"]),
    # P5-T02 jichu / zhenduan templates
    "concept_definition": ("low", []),
    "mechanism": ("medium", ["pathogenesis_summary"]),
    "relation": ("medium", ["relation_summary"]),
    "contrast": ("medium", ["contrast_pair"]),
    "four_exam": ("low", []),
    "symptom_syndrome": ("medium", ["symptom_mapping"]),
    "syndrome": ("high", ["syndrome_mapping"]),
    "differential": ("high", ["differential_diagnosis"]),
    # P5-T03 zhongyao / fangji templates
    "herb_nature_flavor": ("medium", ["herb_nature_flavor"]),
    "herb_function": ("medium", ["herb_function"]),
    "herb_indication": ("medium", ["herb_indication"]),
    "herb_usage": ("high", ["dosage_or_usage"]),
    "herb_toxicity_caution": ("critical", ["toxicity_or_contraindication"]),
    "herb_compatibility": ("medium", ["herb_compatibility"]),
    "herb_contrast": ("medium", ["herb_contrast"]),
    "formula_compatibility": ("medium", ["formula_compatibility"]),
    # P5-T04 neike / zhenjiu / renwen templates
    "acupoint_location": ("high", ["acupoint_location"]),
    "acupoint_indication": ("medium", ["acupoint_indication"]),
    "acupoint_operation": ("high", ["needling_depth_or_direction"]),
    "acupoint_caution": ("critical", ["needling_contraindication"]),
    "meridian_overview": ("low", []),
    "ethics_principle": ("medium", ["ethics_principle"]),
    "regulation_fact": ("high", ["regulation_or_statute"]),
    "ethics_scenario": ("high", ["ethics_scenario"]),
    "history_fact": ("low", []),
    "other": ("medium", ["unclassified_type"]),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CandidateStatus(StrEnum):
    GENERATED = "generated"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    SECOND_REVIEW = "second_review"


class CandidateSourceV2(BaseModel):
    citation_order: int = Field(ge=0)
    chunk_id: str = Field(min_length=1, max_length=256)
    excerpt: str = Field(min_length=1, max_length=100_000)
    pdf_page_index_start: int = Field(ge=0)
    pdf_page_index_end: int = Field(ge=0)
    printed_page_start_label: str | None = None
    printed_page_end_label: str | None = None

    @field_validator("chunk_id", "excerpt")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source text fields must not be blank")
        return normalized

    @field_validator("printed_page_start_label", "printed_page_end_label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_page_range(self) -> CandidateSourceV2:
        if self.pdf_page_index_end < self.pdf_page_index_start:
            raise ValueError("pdf_page_index_end must not precede pdf_page_index_start")
        return self


class CandidateCardV2(BaseModel):
    schema_version: int = Field(default=CANDIDATE_SCHEMA_VERSION)
    id: str = Field(min_length=1, max_length=256)
    document_key: str = Field(min_length=1, max_length=64)
    document_version: str = Field(min_length=1, max_length=128)
    book: str = Field(min_length=1, max_length=128)
    chapter: str | None = None
    section: str | None = None
    card_type: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(min_length=1, max_length=100_000)
    answer_points: list[str] = Field(default_factory=list, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=128)
    source_excerpt: str = Field(min_length=1, max_length=100_000)
    chunk_ids: list[str] = Field(default_factory=list, max_length=64)
    sources: list[CandidateSourceV2] = Field(default_factory=list, max_length=64)
    pdf_page_indexes: list[int] = Field(default_factory=list, max_length=1_000)
    printed_page_labels: list[str] = Field(default_factory=list, max_length=1_000)
    risk_level: RiskLevel
    risk_flags: list[str] = Field(default_factory=list, max_length=64)
    content_hash: str
    status: CandidateStatus
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    generator: str = Field(min_length=1, max_length=128)
    model: str | None = None
    prompt_version: str = Field(min_length=1, max_length=64)
    generation_batch_id: str | None = None
    input_hash: str | None = None
    created_at: str = Field(min_length=1, max_length=64)
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_notes: str | None = None
    review_decision: ReviewDecision | None = None
    legacy: dict[str, Any] | None = None

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != CANDIDATE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {CANDIDATE_SCHEMA_VERSION}")
        return value

    @field_validator("document_key", mode="before")
    @classmethod
    def normalize_document_key(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator(
        "id",
        "document_version",
        "book",
        "card_type",
        "question",
        "answer",
        "source_excerpt",
        "generator",
        "prompt_version",
        "created_at",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required text fields must not be blank")
        return normalized

    @field_validator(
        "chapter",
        "section",
        "model",
        "generation_batch_id",
        "reviewer",
        "reviewed_at",
        "review_notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("answer_points", "tags", "chunk_ids", "risk_flags", "printed_page_labels")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("list values must not be blank")
            if text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @field_validator("pdf_page_indexes")
    @classmethod
    def normalize_page_indexes(cls, value: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for page in value:
            if page < 0:
                raise ValueError("pdf_page_indexes must be >= 0")
            if page in seen:
                continue
            seen.add(page)
            normalized.append(page)
        return normalized

    @field_validator("content_hash", "input_hash")
    @classmethod
    def normalize_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.strip().lower()
        if not _SHA256_RE.fullmatch(lowered):
            raise ValueError("hash fields must be 64 lowercase hex chars")
        return lowered

    @model_validator(mode="after")
    def validate_source_identity(self) -> CandidateCardV2:
        if self.sources:
            orders = sorted(source.citation_order for source in self.sources)
            if orders != list(range(len(self.sources))):
                raise ValueError("citation_order must be contiguous and start at zero")
            chunk_ids = [source.chunk_id for source in self.sources]
            if len(chunk_ids) != len(set(chunk_ids)):
                raise ValueError("a card must not cite the same chunk more than once")
        return self


class CandidateGateError(ValueError):
    """Raised when a candidate fails the schema/provenance/risk gate."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) if self.errors else "candidate gate failed")


def canonical_content_payload(
    *,
    document_version: str,
    card_type: str,
    question: str,
    answer: str,
    answer_points: list[str],
    source_excerpt: str,
    chunk_ids: list[str],
) -> dict[str, Any]:
    return {
        "document_version": document_version,
        "card_type": card_type,
        "question": question,
        "answer": answer,
        "answer_points": answer_points,
        "source_excerpt": source_excerpt,
        "chunk_ids": chunk_ids,
    }


def compute_content_hash(
    *,
    document_version: str,
    card_type: str,
    question: str,
    answer: str,
    answer_points: list[str],
    source_excerpt: str,
    chunk_ids: list[str],
) -> str:
    payload = canonical_content_payload(
        document_version=document_version,
        card_type=card_type,
        question=question,
        answer=answer,
        answer_points=answer_points,
        source_excerpt=source_excerpt,
        chunk_ids=chunk_ids,
    )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_candidate_card_v2_schema() -> dict[str, Any]:
    return json.loads(CANDIDATE_CARD_V2_SCHEMA_PATH.read_text(encoding="utf-8"))


def resolve_document_key(book: str, *, document_key: str | None = None) -> str:
    if document_key:
        return document_key.strip().lower()
    key = BOOK_TO_DOCUMENT_KEY.get(book.strip())
    if not key:
        raise ValueError(f"unknown book for document_key mapping: {book!r}")
    return key


def map_v1_status(status: str | None) -> CandidateStatus:
    raw = (status or "candidate").strip().lower()
    mapping = {
        "candidate": CandidateStatus.GENERATED,
        "generated": CandidateStatus.GENERATED,
        "needs_review": CandidateStatus.NEEDS_REVIEW,
        "approved": CandidateStatus.APPROVED,
        "rejected": CandidateStatus.REJECTED,
        "published": CandidateStatus.PUBLISHED,
        "superseded": CandidateStatus.SUPERSEDED,
    }
    if raw not in mapping:
        raise ValueError(f"unsupported v1 status: {status!r}")
    return mapping[raw]


def infer_risk(card_type: str, *, review_notes: str | None = None) -> tuple[RiskLevel, list[str]]:
    level_name, flags = CARD_TYPE_DEFAULT_RISK.get(card_type, ("medium", ["unclassified_type"]))
    risk_flags = list(flags)
    notes = review_notes or ""
    if "多版本" in notes or "版本" in notes:
        level_name = "critical"
        if "multi_version" not in risk_flags:
            risk_flags.append("multi_version")
    return RiskLevel(level_name), risk_flags


def _as_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    pages: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            pages.append(item)
        elif isinstance(item, str) and item.isdigit():
            pages.append(int(item))
    return pages


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def convert_v1_card_to_v2(
    card: dict[str, Any],
    *,
    document_version: str | None = None,
    document_key: str | None = None,
    chunk_ids: list[str] | None = None,
    sources: list[dict[str, Any]] | None = None,
    pdf_page_indexes: list[int] | None = None,
    printed_page_labels: list[str] | None = None,
    risk_level: str | None = None,
    risk_flags: list[str] | None = None,
    require_sources_for_gate: bool = False,
) -> CandidateCardV2:
    """Convert a v1 candidate card dict into CandidateCardV2.

    Legacy sample cards often lack page/chunk provenance. Conversion still
    succeeds and records placeholders; the gate fails those cards until
    provenance is filled (or explicit overrides are provided).
    """
    if not isinstance(card, dict):
        raise TypeError("card must be a dict")

    book = str(card.get("book") or "").strip()
    if not book:
        raise ValueError("v1 card missing book")
    resolved_key = resolve_document_key(book, document_key=document_key)
    resolved_version = (
        document_version
        or str(card.get("document_version") or "").strip()
        or LEGACY_DOCUMENT_VERSION.get(resolved_key)
    )
    if not resolved_version:
        raise ValueError(f"document_version required for document_key={resolved_key}")

    card_type = str(card.get("type") or card.get("card_type") or "other").strip() or "other"
    question = str(card.get("question") or "").strip()
    answer = str(card.get("answer") or "").strip()
    source_excerpt = str(card.get("source_excerpt") or "").strip()
    answer_points = _as_str_list(card.get("answer_points"))
    tags = _as_str_list(card.get("tags"))

    resolved_chunk_ids = (
        list(chunk_ids) if chunk_ids is not None else _as_str_list(card.get("chunk_ids"))
    )
    if not resolved_chunk_ids:
        # Placeholder for legacy conversion only; gate rejects empty provenance.
        resolved_chunk_ids = []

    resolved_sources_raw = sources if sources is not None else card.get("sources")
    resolved_sources: list[CandidateSourceV2] = []
    if isinstance(resolved_sources_raw, list):
        for idx, item in enumerate(resolved_sources_raw):
            if not isinstance(item, dict):
                continue
            payload = {
                "citation_order": item.get("citation_order", idx),
                "chunk_id": item.get("chunk_id")
                or item.get("document_chunk_id")
                or f"legacy-chunk-{idx}",
                "excerpt": item.get("excerpt")
                or item.get("source_excerpt")
                or source_excerpt
                or question,
                "pdf_page_index_start": item.get("pdf_page_index_start", 0),
                "pdf_page_index_end": item.get(
                    "pdf_page_index_end", item.get("pdf_page_index_start", 0)
                ),
                "printed_page_start_label": item.get("printed_page_start_label"),
                "printed_page_end_label": item.get("printed_page_end_label"),
            }
            resolved_sources.append(CandidateSourceV2.model_validate(payload))

    sample_idxs = _as_int_list(card.get("sample_page_idxs"))
    source_pages = _as_int_list(card.get("source_pages"))
    resolved_pdf_pages = (
        list(pdf_page_indexes)
        if pdf_page_indexes is not None
        else _as_int_list(card.get("pdf_page_indexes")) or sample_idxs
    )
    resolved_printed = (
        list(printed_page_labels)
        if printed_page_labels is not None
        else _as_str_list(card.get("printed_page_labels")) or [str(p) for p in source_pages]
    )

    if risk_level is not None:
        resolved_risk = RiskLevel(risk_level)
        resolved_flags = list(risk_flags or [])
    else:
        inferred_level, inferred_flags = infer_risk(
            card_type, review_notes=str(card.get("review_notes") or "") or None
        )
        resolved_risk = inferred_level
        resolved_flags = list(risk_flags) if risk_flags is not None else inferred_flags

    raw_trace = card.get("trace")
    trace: dict[str, Any] = raw_trace if isinstance(raw_trace, dict) else {}
    generator = str(trace.get("generator") or card.get("generator") or "offline-extractor")
    model = trace.get("model") if trace.get("model") is not None else card.get("model")
    prompt_version = str(trace.get("prompt_version") or card.get("prompt_version") or "v1")
    created_at = str(
        trace.get("created_at") or card.get("created_at") or "1970-01-01T00:00:00+00:00"
    )
    batch_id = trace.get("batch_id") if trace.get("batch_id") is not None else card.get("batch_id")
    status = map_v1_status(str(card.get("status") or "candidate"))

    content_hash = compute_content_hash(
        document_version=resolved_version,
        card_type=card_type,
        question=question,
        answer=answer,
        answer_points=answer_points,
        source_excerpt=source_excerpt,
        chunk_ids=resolved_chunk_ids,
    )

    card_id = str(card.get("id") or "").strip()
    if not card_id:
        raise ValueError("v1 card missing id")

    v2 = CandidateCardV2(
        schema_version=CANDIDATE_SCHEMA_VERSION,
        id=card_id,
        document_key=resolved_key,
        document_version=resolved_version,
        book=book,
        chapter=(str(card["chapter"]).strip() if card.get("chapter") not in (None, "") else None),
        section=(str(card["section"]).strip() if card.get("section") not in (None, "") else None),
        card_type=card_type,
        question=question,
        answer=answer,
        answer_points=answer_points,
        tags=tags,
        source_excerpt=source_excerpt,
        chunk_ids=resolved_chunk_ids,
        sources=resolved_sources,
        pdf_page_indexes=resolved_pdf_pages,
        printed_page_labels=resolved_printed,
        risk_level=resolved_risk,
        risk_flags=resolved_flags,
        content_hash=content_hash,
        status=status,
        confidence=card.get("confidence"),
        generator=generator,
        model=str(model) if model is not None else None,
        prompt_version=prompt_version,
        generation_batch_id=str(batch_id) if batch_id is not None else None,
        input_hash=str(card["input_hash"]).lower() if card.get("input_hash") else None,
        created_at=created_at,
        reviewer=str(card["reviewer"]) if card.get("reviewer") else None,
        reviewed_at=str(card["reviewed_at"]) if card.get("reviewed_at") else None,
        review_notes=str(card["review_notes"])
        if card.get("review_notes") not in (None, "")
        else None,
        review_decision=None,
        legacy={
            "schema_version": 1,
            "source_file": trace.get("source_file"),
            "source_pages": source_pages,
            "sample_page_idxs": sample_idxs,
            "type": card_type,
            "status": card.get("status"),
        },
    )

    # Optional eager gate for callers that already filled provenance.
    if require_sources_for_gate:
        validate_candidate_card_v2(v2)
    return v2


def convert_v1_payload_to_v2(
    payload: dict[str, Any],
    *,
    document_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert a v1 batch payload (with cards[]) into a v2 batch payload."""
    cards_in = payload.get("cards")
    if not isinstance(cards_in, list):
        raise ValueError("v1 payload must contain cards array")

    cards_out: list[dict[str, Any]] = []
    for card in cards_in:
        if not isinstance(card, dict):
            raise ValueError("each card must be an object")
        book = str(card.get("book") or "")
        key = resolve_document_key(book)
        version = None
        if document_versions and key in document_versions:
            version = document_versions[key]
        cards_out.append(
            convert_v1_card_to_v2(card, document_version=version).model_dump(mode="json")
        )

    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "mode": payload.get("mode"),
        "batch_id": payload.get("batch_id"),
        "prompt_version": payload.get("prompt_version"),
        "generated_at": payload.get("generated_at"),
        "count": len(cards_out),
        "cards": cards_out,
        "source_payload_version": payload.get("version", 1),
    }


def gate_candidate_card(card: CandidateCardV2 | dict[str, Any]) -> list[str]:
    """Return gate errors for a candidate card. Empty list means pass."""
    errors: list[str] = []
    try:
        model = card if isinstance(card, CandidateCardV2) else CandidateCardV2.model_validate(card)
    except Exception as exc:  # noqa: BLE001 - collect schema errors as gate failures
        return [f"schema: {exc}"]

    if not model.source_excerpt.strip():
        errors.append("missing source_excerpt")

    has_chunk_ids = bool(model.chunk_ids)
    has_sources = bool(model.sources)
    has_pdf_pages = bool(model.pdf_page_indexes) or any(
        True for source in model.sources if source.pdf_page_index_end >= source.pdf_page_index_start
    )
    if not has_chunk_ids and not has_sources:
        errors.append("missing provenance: chunk_ids/sources required")
    if not has_pdf_pages and not has_sources:
        errors.append("missing pdf page provenance")

    risk_level = (
        model.risk_level
        if isinstance(model.risk_level, RiskLevel)
        else RiskLevel(str(model.risk_level))
    )
    if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} and not model.risk_flags:
        errors.append(f"high-risk card requires risk_flags (risk_level={risk_level.value})")

    expected = compute_content_hash(
        document_version=model.document_version,
        card_type=model.card_type,
        question=model.question,
        answer=model.answer,
        answer_points=list(model.answer_points),
        source_excerpt=model.source_excerpt,
        chunk_ids=list(model.chunk_ids),
    )
    if model.content_hash != expected:
        errors.append("content_hash mismatch")

    status = (
        model.status
        if isinstance(model.status, CandidateStatus)
        else CandidateStatus(str(model.status))
    )
    if status == CandidateStatus.APPROVED and risk_level == RiskLevel.CRITICAL:
        if not model.reviewer or not model.reviewed_at:
            errors.append("critical approved card requires reviewer and reviewed_at")

    return errors


def validate_candidate_card_v2(card: CandidateCardV2 | dict[str, Any]) -> CandidateCardV2:
    """Validate schema + gate. Raises CandidateGateError on failure."""
    model = card if isinstance(card, CandidateCardV2) else CandidateCardV2.model_validate(card)
    errors = gate_candidate_card(model)
    if errors:
        raise CandidateGateError(errors)
    return model


def load_v1_sample_cards(path: Path | None = None) -> list[dict[str, Any]]:
    sample_path = path or (ROOT / "server" / "seed_data" / "candidates_offline_v1.json")
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ValueError(f"invalid sample payload: {sample_path}")
    return [c for c in cards if isinstance(c, dict)]


__all__ = [
    "BOOK_TO_DOCUMENT_KEY",
    "CARD_TYPE_DEFAULT_RISK",
    "CANDIDATE_CARD_V1_SCHEMA_PATH",
    "CANDIDATE_CARD_V2_SCHEMA_PATH",
    "CANDIDATE_SCHEMA_VERSION",
    "CandidateCardV2",
    "CandidateGateError",
    "CandidateSourceV2",
    "CandidateStatus",
    "LEGACY_CANDIDATE_SCHEMA_PATH",
    "LEGACY_DOCUMENT_VERSION",
    "ReviewDecision",
    "RiskLevel",
    "compute_content_hash",
    "convert_v1_card_to_v2",
    "convert_v1_payload_to_v2",
    "gate_candidate_card",
    "infer_risk",
    "load_candidate_card_v2_schema",
    "load_v1_sample_cards",
    "map_v1_status",
    "resolve_document_key",
    "validate_candidate_card_v2",
]
