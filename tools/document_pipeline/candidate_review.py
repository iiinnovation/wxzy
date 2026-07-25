"""Human review workflow for candidate cards (P5-T07).

Initial surface is a static review bundle + pure library/CLI actions:
  - approve / edit / reject / second_review
  - per-card and chapter batch (critical cards cannot batch-approve)
  - full audit trail
  - edits re-run schema + automated validation

Reviewed cards remain non-learning artifacts until publication import.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.candidate_schema import (
    CandidateCardV2,
    CandidateStatus,
    ReviewDecision,
    RiskLevel,
    compute_content_hash,
    validate_candidate_card_v2,
)
from tools.document_pipeline.candidate_validation import (
    CardValidationResult,
    validate_card,
)

STAGE = "candidate_review"
STAGE_VERSION = "p5t07-v1"

DECISIONS = {
    "approve": ReviewDecision.APPROVE,
    "edit": ReviewDecision.EDIT,
    "reject": ReviewDecision.REJECT,
    "second_review": ReviewDecision.SECOND_REVIEW,
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_model(card: CandidateCardV2 | dict[str, Any]) -> CandidateCardV2:
    return card if isinstance(card, CandidateCardV2) else CandidateCardV2.model_validate(card)


def _risk(card: CandidateCardV2) -> RiskLevel:
    return card.risk_level if isinstance(card.risk_level, RiskLevel) else RiskLevel(str(card.risk_level))


def _recompute_hash(card: CandidateCardV2) -> CandidateCardV2:
    content_hash = compute_content_hash(
        document_version=card.document_version,
        card_type=card.card_type,
        question=card.question,
        answer=card.answer,
        answer_points=list(card.answer_points or []),
        source_excerpt=card.source_excerpt,
        chunk_ids=list(card.chunk_ids or []),
    )
    if card.content_hash == content_hash:
        return card
    return card.model_copy(update={"content_hash": content_hash})


@dataclass
class AuditEvent:
    event_id: str
    action: str
    card_id: str
    reviewer: str
    at: str
    notes: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    batch_id: str | None = None
    validation: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "card_id": self.card_id,
            "reviewer": self.reviewer,
            "at": self.at,
            "notes": self.notes,
            "before": self.before,
            "after": self.after,
            "batch_id": self.batch_id,
            "validation": self.validation,
            "error": self.error,
        }


@dataclass
class ReviewActionResult:
    ok: bool
    card: CandidateCardV2 | None
    audit: AuditEvent
    validation: CardValidationResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "card_id": self.card.id if self.card is not None else self.audit.card_id,
            "error": self.error,
            "audit": self.audit.to_dict(),
            "validation": None
            if self.validation is None
            else {
                "ok": self.validation.ok,
                "issues": [i.to_dict() for i in self.validation.issues],
            },
        }


@dataclass
class ReviewBundle:
    cards: dict[str, CandidateCardV2]
    audit: list[AuditEvent] = field(default_factory=list)
    document_version: str | None = None
    generation_batch_id: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    stage: str = STAGE
    stage_version: str = STAGE_VERSION
    _event_seq: int = 0

    @classmethod
    def from_cards(
        cls,
        cards: Sequence[CandidateCardV2 | dict[str, Any]],
        *,
        document_version: str | None = None,
        generation_batch_id: str | None = None,
    ) -> ReviewBundle:
        mapped: dict[str, CandidateCardV2] = {}
        for raw in cards:
            card = _recompute_hash(_as_model(raw))
            if card.id in mapped:
                raise ValueError(f"duplicate card id in review bundle: {card.id}")
            mapped[card.id] = card
        doc_versions = {c.document_version for c in mapped.values()}
        return cls(
            cards=mapped,
            document_version=document_version or (next(iter(doc_versions)) if len(doc_versions) == 1 else None),
            generation_batch_id=generation_batch_id,
        )

    def _next_event_id(self) -> str:
        self._event_seq += 1
        return f"evt-{self._event_seq:04d}"

    def get(self, card_id: str) -> CandidateCardV2:
        if card_id not in self.cards:
            raise KeyError(f"card not in bundle: {card_id}")
        return self.cards[card_id]

    def cards_for_chapter(self, chapter: str) -> list[CandidateCardV2]:
        return [c for c in self.cards.values() if (c.chapter or "") == chapter]

    def _record(self, event: AuditEvent) -> None:
        self.audit.append(event)
        self.updated_at = event.at

    def apply_decision(
        self,
        card_id: str,
        *,
        action: str,
        reviewer: str,
        notes: str | None = None,
        edits: dict[str, Any] | None = None,
        batch_id: str | None = None,
        allow_critical_batch: bool = False,
    ) -> ReviewActionResult:
        """Apply one review decision to a card.

        action: approve | edit | reject | second_review
        """
        action_key = action.strip().lower()
        if action_key not in DECISIONS:
            raise ValueError(f"unsupported review action: {action}")
        if not reviewer or not reviewer.strip():
            raise ValueError("reviewer is required")

        at = now_iso()
        try:
            card = self.get(card_id)
        except KeyError as exc:
            event = AuditEvent(
                event_id=self._next_event_id(),
                action=action_key,
                card_id=card_id,
                reviewer=reviewer,
                at=at,
                notes=notes,
                batch_id=batch_id,
                error=str(exc),
            )
            self._record(event)
            return ReviewActionResult(ok=False, card=None, audit=event, error=str(exc))

        if batch_id and _risk(card) == RiskLevel.CRITICAL and not allow_critical_batch:
            if action_key in {"approve", "edit"}:
                msg = "critical cards cannot be batch-approved/edited"
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action=action_key,
                    card_id=card_id,
                    reviewer=reviewer,
                    at=at,
                    notes=notes,
                    before=_public_card_view(card),
                    batch_id=batch_id,
                    error=msg,
                )
                self._record(event)
                return ReviewActionResult(ok=False, card=card, audit=event, error=msg)

        before = _public_card_view(card)
        updates: dict[str, Any] = {
            "reviewer": reviewer.strip(),
            "reviewed_at": at,
            "review_notes": notes,
            "review_decision": DECISIONS[action_key],
        }
        validation: CardValidationResult | None = None

        if action_key == "approve":
            updates["status"] = CandidateStatus.APPROVED
        elif action_key == "reject":
            updates["status"] = CandidateStatus.REJECTED
        elif action_key == "second_review":
            updates["status"] = CandidateStatus.NEEDS_REVIEW
        elif action_key == "edit":
            if not edits:
                msg = "edit action requires edits payload"
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action=action_key,
                    card_id=card_id,
                    reviewer=reviewer,
                    at=at,
                    notes=notes,
                    before=before,
                    batch_id=batch_id,
                    error=msg,
                )
                self._record(event)
                return ReviewActionResult(ok=False, card=card, audit=event, error=msg)
            allowed = {
                "question",
                "answer",
                "answer_points",
                "tags",
                "source_excerpt",
                "chapter",
                "section",
                "card_type",
                "risk_level",
                "risk_flags",
            }
            unknown = sorted(set(edits) - allowed)
            if unknown:
                msg = f"unsupported edit fields: {', '.join(unknown)}"
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action=action_key,
                    card_id=card_id,
                    reviewer=reviewer,
                    at=at,
                    notes=notes,
                    before=before,
                    batch_id=batch_id,
                    error=msg,
                )
                self._record(event)
                return ReviewActionResult(ok=False, card=card, audit=event, error=msg)
            updates.update({k: edits[k] for k in allowed if k in edits})
            updates["status"] = CandidateStatus.NEEDS_REVIEW
            updates["review_decision"] = ReviewDecision.EDIT

        try:
            updated = _recompute_hash(card.model_copy(update=updates))
            # schema/provenance gate first
            updated = validate_candidate_card_v2(updated)
            # automated validation after content-affecting edits (and as a soft check on approve)
            validation = validate_card(updated)
            if action_key == "edit" and not validation.ok:
                msg = "edit failed automated validation: " + "; ".join(
                    f"{i.code}: {i.message}" for i in validation.issues
                )
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action=action_key,
                    card_id=card_id,
                    reviewer=reviewer,
                    at=at,
                    notes=notes,
                    before=before,
                    after=_public_card_view(updated),
                    batch_id=batch_id,
                    validation={
                        "ok": validation.ok,
                        "issues": [i.to_dict() for i in validation.issues],
                    },
                    error=msg,
                )
                self._record(event)
                return ReviewActionResult(
                    ok=False,
                    card=card,
                    audit=event,
                    validation=validation,
                    error=msg,
                )
            # approve still records validation issues but blocks if validation fails
            if action_key == "approve" and validation is not None and not validation.ok:
                msg = "approve blocked by automated validation: " + "; ".join(
                    f"{i.code}: {i.message}" for i in validation.issues
                )
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action=action_key,
                    card_id=card_id,
                    reviewer=reviewer,
                    at=at,
                    notes=notes,
                    before=before,
                    after=_public_card_view(updated),
                    batch_id=batch_id,
                    validation={
                        "ok": validation.ok,
                        "issues": [i.to_dict() for i in validation.issues],
                    },
                    error=msg,
                )
                self._record(event)
                return ReviewActionResult(
                    ok=False,
                    card=card,
                    audit=event,
                    validation=validation,
                    error=msg,
                )

            self.cards[card_id] = updated
            event = AuditEvent(
                event_id=self._next_event_id(),
                action=action_key,
                card_id=card_id,
                reviewer=reviewer,
                at=at,
                notes=notes,
                before=before,
                after=_public_card_view(updated),
                batch_id=batch_id,
                validation=None
                if validation is None
                else {
                    "ok": validation.ok,
                    "issues": [i.to_dict() for i in validation.issues],
                },
            )
            self._record(event)
            return ReviewActionResult(ok=True, card=updated, audit=event, validation=validation)
        except Exception as exc:  # noqa: BLE001 - audit failures
            event = AuditEvent(
                event_id=self._next_event_id(),
                action=action_key,
                card_id=card_id,
                reviewer=reviewer,
                at=at,
                notes=notes,
                before=before,
                batch_id=batch_id,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._record(event)
            return ReviewActionResult(ok=False, card=card, audit=event, error=str(exc))

    def batch_approve_chapter(
        self,
        chapter: str,
        *,
        reviewer: str,
        notes: str | None = None,
        risk_levels: Iterable[str] | None = None,
    ) -> list[ReviewActionResult]:
        """Batch-approve cards in a chapter.

        Critical cards are always skipped/rejected by policy.
        Default risk filter: low + medium only.
        """
        allowed_risks = {
            RiskLevel(x) for x in (risk_levels or [RiskLevel.LOW.value, RiskLevel.MEDIUM.value])
        }
        batch_id = f"batch-{now_iso()}"
        results: list[ReviewActionResult] = []
        for card in self.cards_for_chapter(chapter):
            if _risk(card) == RiskLevel.CRITICAL or _risk(card) not in allowed_risks:
                # explicit audit skip for policy
                event = AuditEvent(
                    event_id=self._next_event_id(),
                    action="batch_skip",
                    card_id=card.id,
                    reviewer=reviewer,
                    at=now_iso(),
                    notes=notes,
                    before=_public_card_view(card),
                    batch_id=batch_id,
                    error=f"skipped: risk_level={_risk(card).value} not batch-approvable",
                )
                self._record(event)
                results.append(
                    ReviewActionResult(
                        ok=False,
                        card=card,
                        audit=event,
                        error=event.error,
                    )
                )
                continue
            results.append(
                self.apply_decision(
                    card.id,
                    action="approve",
                    reviewer=reviewer,
                    notes=notes,
                    batch_id=batch_id,
                )
            )
        return results

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_version": self.stage_version,
            "document_version": self.document_version,
            "generation_batch_id": self.generation_batch_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": "candidate_review_only",
            "card_count": len(self.cards),
            "cards": [c.model_dump(mode="json") for c in self.cards.values()],
            "audit": [e.to_dict() for e in self.audit],
            "by_status": _count_by(self.cards.values(), key=lambda c: str(c.status.value if hasattr(c.status, 'value') else c.status)),
            "by_decision": _count_by(
                [c for c in self.cards.values() if c.review_decision is not None],
                key=lambda c: str(c.review_decision.value if hasattr(c.review_decision, 'value') else c.review_decision),
            ),
        }

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        (out_dir / "review_bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "audit.jsonl").write_text(
            "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in self.audit),
            encoding="utf-8",
        )
        (out_dir / "cards.jsonl").write_text(
            "".join(
                json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for c in self.cards.values()
            ),
            encoding="utf-8",
        )
        (out_dir / "REVIEW.md").write_text(render_review_markdown(self), encoding="utf-8")


def _public_card_view(card: CandidateCardV2) -> dict[str, Any]:
    return {
        "id": card.id,
        "status": str(card.status.value if hasattr(card.status, "value") else card.status),
        "risk_level": str(card.risk_level.value if hasattr(card.risk_level, "value") else card.risk_level),
        "question": card.question,
        "answer": card.answer,
        "answer_points": list(card.answer_points or []),
        "review_decision": None
        if card.review_decision is None
        else str(card.review_decision.value if hasattr(card.review_decision, "value") else card.review_decision),
        "reviewer": card.reviewer,
        "reviewed_at": card.reviewed_at,
        "content_hash": card.content_hash,
    }


def _count_by(items: Iterable[CandidateCardV2], *, key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = key(item)
        out[k] = out.get(k, 0) + 1
    return out


def render_review_markdown(bundle: ReviewBundle) -> str:
    lines = [
        f"# Candidate Review Bundle ({bundle.stage_version})",
        "",
        f"- document_version: `{bundle.document_version or 'mixed/unknown'}`",
        f"- cards: {len(bundle.cards)}",
        f"- audit events: {len(bundle.audit)}",
        f"- updated_at: {bundle.updated_at}",
        "",
        "## Cards",
        "",
    ]
    for card in bundle.cards.values():
        lines.extend(
            [
                f"### {card.id}",
                f"- book/chapter: {card.book} / {card.chapter or '-'}",
                f"- type/risk: {card.card_type} / {card.risk_level}",
                f"- status/decision: {card.status} / {card.review_decision or '-'}",
                f"- question: {card.question}",
                f"- answer: {card.answer}",
                f"- source: {card.source_excerpt[:180]}",
                f"- reviewer: {card.reviewer or '-'}",
                "",
            ]
        )
    if bundle.audit:
        lines.extend(["## Audit", ""])
        for event in bundle.audit:
            lines.append(
                f"- `{event.at}` {event.action} `{event.card_id}` by {event.reviewer}"
                + (f" — {event.notes}" if event.notes else "")
                + (f" ERROR: {event.error}" if event.error else "")
            )
        lines.append("")
    return "\n".join(lines)


def load_review_bundle(path: Path | str) -> ReviewBundle:
    p = path if isinstance(path, Path) else Path(str(path))
    data = json.loads(p.read_text(encoding="utf-8"))
    cards = data.get("cards") or []
    bundle = ReviewBundle.from_cards(
        cards,
        document_version=data.get("document_version"),
        generation_batch_id=data.get("generation_batch_id"),
    )
    bundle.created_at = str(data.get("created_at") or bundle.created_at)
    bundle.updated_at = str(data.get("updated_at") or bundle.updated_at)
    # restore audit as read-only history; event ids continue after max
    for item in data.get("audit") or []:
        bundle.audit.append(
            AuditEvent(
                event_id=str(item.get("event_id") or bundle._next_event_id()),
                action=str(item.get("action") or ""),
                card_id=str(item.get("card_id") or ""),
                reviewer=str(item.get("reviewer") or ""),
                at=str(item.get("at") or now_iso()),
                notes=item.get("notes"),
                before=item.get("before"),
                after=item.get("after"),
                batch_id=item.get("batch_id"),
                validation=item.get("validation"),
                error=item.get("error"),
            )
        )
    # keep event seq above restored ids when possible
    nums = []
    for e in bundle.audit:
        if e.event_id.startswith("evt-"):
            try:
                nums.append(int(e.event_id.split("-", 1)[1]))
            except ValueError:
                continue
    if nums:
        bundle._event_seq = max(nums)
    return bundle


__all__ = [
    "STAGE",
    "STAGE_VERSION",
    "AuditEvent",
    "ReviewActionResult",
    "ReviewBundle",
    "load_review_bundle",
    "render_review_markdown",
]
