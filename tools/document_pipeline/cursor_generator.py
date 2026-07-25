"""ContentBlock cursor candidate generator (P5-T05).

Walks ordered ContentBlocks instead of `md[:max_chars]`. Each request records:
chunk IDs, input hash, model/prompt, token/cost, candidate IDs, and errors.
Successful chunk cursors are resumable; repeated runs do not duplicate candidates.
Outputs remain candidates only.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.candidate_schema import (
    CandidateCardV2,
    CandidateSourceV2,
    compute_content_hash,
    validate_candidate_card_v2,
)
from tools.document_pipeline.templates_jichu_zhenduan import extract_jichu_zhenduan_cards
from tools.document_pipeline.templates_neike_zhenjiu_renwen import (
    extract_neike_zhenjiu_renwen_cards,
)
from tools.document_pipeline.templates_zhongyao_fangji import extract_zhongyao_fangji_cards

GENERATOR = "contentblock-cursor-generator"
PROMPT_VERSION = "p5t05-v1"
STAGE = "candidate_generation"
STAGE_VERSION = "p5t05-v1"

ModelCaller = Callable[..., list[dict[str, Any]]]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_content_blocks(source: Path | str | Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Load ContentBlocks from list/json/jsonl path."""
    if isinstance(source, (list, tuple)):
        blocks = [dict(b) for b in source]
    else:
        path = source if isinstance(source, Path) else Path(str(source))
        raw = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            blocks = [json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            data = json.loads(raw)
            if isinstance(data, dict) and "content_blocks" in data:
                blocks = list(data["content_blocks"])
            elif isinstance(data, list):
                blocks = data
            else:
                raise ValueError(f"unsupported content block payload: {path}")
    if not blocks:
        raise ValueError("content_blocks must be non-empty")
    # normalize required fields
    out: list[dict[str, Any]] = []
    for i, b in enumerate(blocks, start=1):
        block = dict(b)
        text = block.get("cleaned_text") or block.get("text") or ""
        if not str(text).strip():
            continue
        block.setdefault("ordinal", i)
        block.setdefault("id", f"block-{i}")
        block.setdefault("block_type", block.get("type") or "text")
        block.setdefault("chapter_path", block.get("chapter_path") or [])
        block.setdefault("source_pdf_pages", block.get("source_pdf_pages") or [])
        block.setdefault("printed_page_labels", block.get("printed_page_labels") or [])
        block["cleaned_text"] = str(text)
        out.append(block)
    if not out:
        raise ValueError("no non-empty content blocks")
    out.sort(key=lambda b: int(b.get("ordinal") or 0))
    return out


def pack_blocks(
    blocks: Sequence[dict[str, Any]],
    *,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    """Pack ordered blocks into windows that each stay within max_chars.

    A single oversized block becomes its own window (never truncated silently).
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    for block in blocks:
        text = str(block.get("cleaned_text") or "")
        # separators between packed blocks
        add_len = len(text) + (2 if current else 0)
        if current and current_len + add_len > max_chars:
            windows.append(current)
            current = [block]
            current_len = len(text)
            continue
        if not current and len(text) > max_chars:
            windows.append([block])
            current = []
            current_len = 0
            continue
        current.append(block)
        current_len += add_len
    if current:
        windows.append(current)
    return windows


def compute_input_hash(
    *,
    document_version: str,
    chunk_ids: Sequence[str],
    texts: Sequence[str],
    book_template: str,
    prompt_version: str,
    model: str | None,
) -> str:
    payload = {
        "document_version": document_version,
        "chunk_ids": list(chunk_ids),
        "texts": list(texts),
        "book_template": book_template,
        "prompt_version": prompt_version,
        "model": model,
        "stage_version": STAGE_VERSION,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _book_name(book_template: str) -> str:
    mapping = {
        "jichu": "中医基础理论",
        "zhenduan": "中医诊断学",
        "zhongyao": "中药学",
        "fangji": "方剂学",
        "neike": "中医内科学",
        "zhenjiu": "针灸学",
        "renwen": "人文",
    }
    return mapping.get(book_template, book_template)


def extract_cards_for_template(
    md: str,
    *,
    book_template: str,
    document_version: str,
    chunk_id_prefix: str,
    generation_batch_id: str | None,
    pdf_page_index: int = 0,
    printed_page_label: str = "1",
) -> list[CandidateCardV2]:
    """Dispatch deterministic template extractors for one window of text."""
    key = book_template.strip().lower()
    if key in {"jichu", "zhenduan"}:
        return extract_jichu_zhenduan_cards(
            md,
            book_template=key,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key in {"zhongyao", "fangji"}:
        return extract_zhongyao_fangji_cards(
            md,
            book_template=key,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    if key in {"neike", "zhenjiu", "renwen"}:
        return extract_neike_zhenjiu_renwen_cards(
            md,
            book_template=key,
            document_version=document_version,
            generation_batch_id=generation_batch_id,
            chunk_id_prefix=chunk_id_prefix,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
        )
    raise ValueError(f"unsupported book_template for cursor generator: {book_template!r}")


def _attach_window_provenance(
    cards: Iterable[CandidateCardV2],
    *,
    window_blocks: Sequence[dict[str, Any]],
    input_hash: str,
    model: str | None,
    generator: str,
    prompt_version: str,
) -> list[CandidateCardV2]:
    chunk_ids = [str(b["id"]) for b in window_blocks]
    pdf_pages: list[int] = []
    labels: list[str] = []
    for b in window_blocks:
        for p in b.get("source_pdf_pages") or []:
            try:
                pdf_pages.append(int(p))
            except (TypeError, ValueError):
                continue
        for lab in b.get("printed_page_labels") or []:
            if lab is not None and str(lab) not in labels:
                labels.append(str(lab))
    pdf_pages = sorted(set(pdf_pages))
    primary = window_blocks[0]
    chapter_path = primary.get("chapter_path") or []
    chapter = chapter_path[0] if chapter_path else None
    section = chapter_path[-1] if len(chapter_path) >= 2 else (chapter_path[0] if chapter_path else None)
    out: list[CandidateCardV2] = []
    for card in cards:
        # keep extractor chunk_ids if present, but always include window chunk ids
        merged_chunks = list(dict.fromkeys([*chunk_ids, *list(card.chunk_ids or [])]))
        sources = list(card.sources)
        # ensure every window chunk is represented at least once
        existing = {s.chunk_id for s in sources}
        for idx, cid in enumerate(chunk_ids):
            if cid in existing:
                continue
            block = window_blocks[idx]
            pages = block.get("source_pdf_pages") or [0]
            try:
                page = int(pages[0]) if pages else 0
            except (TypeError, ValueError):
                page = 0
            plabels = block.get("printed_page_labels") or []
            label = str(plabels[0]) if plabels else None
            sources.append(
                CandidateSourceV2(
                    citation_order=len(sources),
                    chunk_id=cid,
                    excerpt=(block.get("cleaned_text") or "")[:500] or card.source_excerpt,
                    pdf_page_index_start=page,
                    pdf_page_index_end=page,
                    printed_page_start_label=label,
                    printed_page_end_label=label,
                )
            )
        updates: dict[str, Any] = {
            "chunk_ids": merged_chunks,
            "sources": sources,
            "input_hash": input_hash,
            "generator": generator,
            "prompt_version": prompt_version,
            "model": model,
            "content_hash": compute_content_hash(
                document_version=card.document_version,
                card_type=card.card_type,
                question=card.question,
                answer=card.answer,
                answer_points=list(card.answer_points or []),
                source_excerpt=card.source_excerpt,
                chunk_ids=merged_chunks,
            ),
        }
        if pdf_pages:
            updates["pdf_page_indexes"] = pdf_pages
        if labels:
            updates["printed_page_labels"] = labels
        if chapter and not card.chapter:
            updates["chapter"] = chapter
        if section and not card.section:
            updates["section"] = section
        out.append(validate_candidate_card_v2(card.model_copy(update=updates)))
    return out


@dataclass
class CursorState:
    document_version: str
    book_template: str
    generation_batch_id: str
    generation_version: str = STAGE_VERSION
    completed_chunk_ids: list[str] = field(default_factory=list)
    completed_input_hashes: list[str] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    candidate_content_hashes: list[str] = field(default_factory=list)
    last_success_ordinal: int | None = None
    last_success_chunk_id: str | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=now_iso)

    @classmethod
    def load(cls, path: Path) -> CursorState:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            document_version=str(data["document_version"]),
            book_template=str(data["book_template"]),
            generation_batch_id=str(data["generation_batch_id"]),
            generation_version=str(data.get("generation_version") or STAGE_VERSION),
            completed_chunk_ids=list(data.get("completed_chunk_ids") or []),
            completed_input_hashes=list(data.get("completed_input_hashes") or []),
            candidate_ids=list(data.get("candidate_ids") or []),
            candidate_content_hashes=list(data.get("candidate_content_hashes") or []),
            last_success_ordinal=data.get("last_success_ordinal"),
            last_success_chunk_id=data.get("last_success_chunk_id"),
            requests=list(data.get("requests") or []),
            updated_at=str(data.get("updated_at") or now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": STAGE,
            "stage_version": STAGE_VERSION,
            "generation_version": self.generation_version,
            "document_version": self.document_version,
            "book_template": self.book_template,
            "generation_batch_id": self.generation_batch_id,
            "completed_chunk_ids": self.completed_chunk_ids,
            "completed_input_hashes": self.completed_input_hashes,
            "candidate_ids": self.candidate_ids,
            "candidate_content_hashes": self.candidate_content_hashes,
            "last_success_ordinal": self.last_success_ordinal,
            "last_success_chunk_id": self.last_success_chunk_id,
            "requests": self.requests,
            "updated_at": self.updated_at,
        }

    def save(self, path: Path) -> None:
        self.updated_at = now_iso()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class CursorRunResult:
    cards: list[CandidateCardV2]
    state: CursorState
    covered_chunk_ids: list[str]
    windows_total: int
    windows_processed: int
    windows_skipped: int
    mode: str

    def to_manifest(self) -> dict[str, Any]:
        return {
            "stage": STAGE,
            "stage_version": STAGE_VERSION,
            "mode": self.mode,
            "document_version": self.state.document_version,
            "book_template": self.state.book_template,
            "generation_batch_id": self.state.generation_batch_id,
            "generator": GENERATOR,
            "prompt_version": PROMPT_VERSION,
            "windows_total": self.windows_total,
            "windows_processed": self.windows_processed,
            "windows_skipped": self.windows_skipped,
            "covered_chunk_ids": self.covered_chunk_ids,
            "candidate_count": len(self.cards),
            "candidate_ids": [c.id for c in self.cards],
            "status": "candidate_only",
            "generated_at": now_iso(),
        }


def _window_text(blocks: Sequence[dict[str, Any]]) -> str:
    return "\n\n".join(str(b.get("cleaned_text") or "") for b in blocks)


def _default_page_meta(blocks: Sequence[dict[str, Any]]) -> tuple[int, str]:
    pages = blocks[0].get("source_pdf_pages") or [0]
    try:
        page = int(pages[0]) if pages else 0
    except (TypeError, ValueError):
        page = 0
    labels = blocks[0].get("printed_page_labels") or ["1"]
    label = str(labels[0]) if labels else "1"
    return page, label


def run_cursor_generation(
    blocks: Sequence[dict[str, Any]] | Path | str,
    *,
    book_template: str,
    document_version: str,
    generation_batch_id: str,
    max_chars: int = 12000,
    mode: str = "offline",
    model: str | None = None,
    model_caller: ModelCaller | None = None,
    state_path: Path | None = None,
    out_dir: Path | None = None,
    resume: bool = True,
    fail_on_error: bool = False,
) -> CursorRunResult:
    """Generate candidates by ContentBlock cursor.

    mode:
      - offline: deterministic template extractors (default for tests/CI)
      - api: requires model_caller; never truncates the whole document
    """
    loaded = load_content_blocks(blocks)
    windows = pack_blocks(loaded, max_chars=max_chars)
    state = None
    if resume and state_path and state_path.exists():
        state = CursorState.load(state_path)
        if state.document_version != document_version or state.book_template != book_template:
            raise ValueError("state document_version/book_template mismatch")
    if state is None:
        state = CursorState(
            document_version=document_version,
            book_template=book_template,
            generation_batch_id=generation_batch_id,
        )

    completed = set(state.completed_chunk_ids)
    seen_hashes = set(state.candidate_content_hashes)
    cards: list[CandidateCardV2] = []
    # Always reload previous candidates on resume so a no-op second run
    # still returns the same card set and does not rewrite an empty file.
    if out_dir and (out_dir / "candidates.jsonl").exists() and resume:
        loaded_hashes: set[str] = set()
        for line in (out_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = validate_candidate_card_v2(json.loads(line))
            if card.content_hash in loaded_hashes:
                continue
            cards.append(card)
            loaded_hashes.add(card.content_hash)
            seen_hashes.add(card.content_hash)

    covered: list[str] = []
    processed = 0
    skipped = 0
    mode_norm = mode.strip().lower()
    if mode_norm not in {"offline", "api"}:
        raise ValueError("mode must be offline|api")
    if mode_norm == "api" and model_caller is None:
        raise ValueError("api mode requires model_caller")

    for window in windows:
        chunk_ids = [str(b["id"]) for b in window]
        covered.extend(chunk_ids)
        if all(cid in completed for cid in chunk_ids):
            skipped += 1
            continue
        texts = [str(b.get("cleaned_text") or "") for b in window]
        input_hash = compute_input_hash(
            document_version=document_version,
            chunk_ids=chunk_ids,
            texts=texts,
            book_template=book_template,
            prompt_version=PROMPT_VERSION,
            model=model if mode_norm == "api" else None,
        )
        if input_hash in set(state.completed_input_hashes) and all(cid in completed for cid in chunk_ids):
            skipped += 1
            continue

        req: dict[str, Any] = {
            "chunk_ids": chunk_ids,
            "input_hash": input_hash,
            "model": model if mode_norm == "api" else None,
            "prompt_version": PROMPT_VERSION,
            "generator": GENERATOR,
            "mode": mode_norm,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost": 0.0,
            "candidate_ids": [],
            "status": "pending",
            "error": None,
            "started_at": now_iso(),
        }
        try:
            page, label = _default_page_meta(window)
            text = _window_text(window)
            if mode_norm == "offline":
                raw_cards = extract_cards_for_template(
                    text,
                    book_template=book_template,
                    document_version=document_version,
                    chunk_id_prefix=f"{chunk_ids[0]}.x",
                    generation_batch_id=generation_batch_id,
                    pdf_page_index=page,
                    printed_page_label=label,
                )
                window_cards = _attach_window_provenance(
                    raw_cards,
                    window_blocks=window,
                    input_hash=input_hash,
                    model=None,
                    generator=GENERATOR,
                    prompt_version=PROMPT_VERSION,
                )
                # approximate offline token usage by chars
                req["token_usage"] = {
                    "prompt_tokens": max(1, len(text) // 4),
                    "completion_tokens": max(0, sum(len(c.answer) for c in window_cards) // 4),
                    "total_tokens": max(1, len(text) // 4)
                    + max(0, sum(len(c.answer) for c in window_cards) // 4),
                }
            else:
                if model_caller is None:
                    raise ValueError("api mode requires model_caller")
                api_cards = model_caller(
                    text,
                    book=_book_name(book_template),
                    model=model,
                    chunk_ids=chunk_ids,
                    input_hash=input_hash,
                )
                # model_caller may return usage via attribute
                usage = getattr(model_caller, "last_usage", None)
                if isinstance(usage, dict):
                    req["token_usage"] = {
                        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or 0),
                        "total_tokens": int(usage.get("total_tokens") or 0),
                    }
                    req["cost"] = float(usage.get("cost") or 0.0)
                # convert bare dicts via offline extract if caller returns nothing useful?
                # Expect list[dict] already candidate-like; validate through schema with help of templates if needed.
                window_cards = []
                for raw in api_cards:
                    if isinstance(raw, CandidateCardV2):
                        card = raw
                    else:
                        # minimal coercion: require v2-shaped dict
                        card = validate_candidate_card_v2(raw)
                    window_cards.append(card)
                window_cards = _attach_window_provenance(
                    window_cards,
                    window_blocks=window,
                    input_hash=input_hash,
                    model=model,
                    generator=GENERATOR,
                    prompt_version=PROMPT_VERSION,
                )

            new_cards: list[CandidateCardV2] = []
            for card in window_cards:
                if card.content_hash in seen_hashes:
                    continue
                seen_hashes.add(card.content_hash)
                new_cards.append(card)
                cards.append(card)
                state.candidate_ids.append(card.id)
                state.candidate_content_hashes.append(card.content_hash)

            req["candidate_ids"] = [c.id for c in new_cards]
            req["status"] = "success"
            req["finished_at"] = now_iso()
            for cid in chunk_ids:
                if cid not in completed:
                    completed.add(cid)
                    state.completed_chunk_ids.append(cid)
            if input_hash not in state.completed_input_hashes:
                state.completed_input_hashes.append(input_hash)
            state.last_success_ordinal = int(window[-1].get("ordinal") or 0)
            state.last_success_chunk_id = chunk_ids[-1]
            processed += 1
        except Exception as exc:  # noqa: BLE001 - record and optionally continue
            req["status"] = "error"
            req["error"] = f"{type(exc).__name__}: {exc}"
            req["finished_at"] = now_iso()
            state.requests.append(req)
            if state_path:
                state.save(state_path)
            if fail_on_error:
                raise
            # leave cursor before failed window for resume
            continue

        state.requests.append(req)
        if state_path:
            state.save(state_path)
        if out_dir:
            _append_candidates(out_dir, new_cards)

    # final artifacts
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        # rewrite candidates.jsonl canonically
        (out_dir / "candidates.jsonl").write_text(
            "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n" for c in cards),
            encoding="utf-8",
        )
        result = CursorRunResult(
            cards=cards,
            state=state,
            covered_chunk_ids=list(dict.fromkeys(covered)),
            windows_total=len(windows),
            windows_processed=processed,
            windows_skipped=skipped,
            mode=mode_norm,
        )
        (out_dir / "manifest.json").write_text(
            json.dumps(result.to_manifest(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "requests.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in state.requests),
            encoding="utf-8",
        )
        if state_path is None:
            state_path = out_dir / "cursor_state.json"
        state.save(state_path)
        return result

    return CursorRunResult(
        cards=cards,
        state=state,
        covered_chunk_ids=list(dict.fromkeys(covered)),
        windows_total=len(windows),
        windows_processed=processed,
        windows_skipped=skipped,
        mode=mode_norm,
    )


def _append_candidates(out_dir: Path, cards: Sequence[CandidateCardV2]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "candidates.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for card in cards:
            fh.write(json.dumps(card.model_dump(mode="json"), ensure_ascii=False) + "\n")


def assert_full_coverage(
    blocks: Sequence[dict[str, Any]],
    covered_chunk_ids: Sequence[str],
) -> None:
    expected = [str(b["id"]) for b in load_content_blocks(blocks)]
    missing = [cid for cid in expected if cid not in set(covered_chunk_ids)]
    if missing:
        raise AssertionError(f"cursor missed chunk ids: {missing[:10]}")


__all__ = [
    "GENERATOR",
    "PROMPT_VERSION",
    "STAGE",
    "STAGE_VERSION",
    "CursorRunResult",
    "CursorState",
    "assert_full_coverage",
    "compute_input_hash",
    "extract_cards_for_template",
    "load_content_blocks",
    "pack_blocks",
    "run_cursor_generation",
    "sha256_text",
]
