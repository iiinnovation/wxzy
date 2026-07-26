from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..catalog.models import Card
from ..catalog.services import _legacy_list
from ..identity.models import User
from .models import CardEnrollment, CardIssue, ReviewAttempt
from .schemas import (
    CardIssueType,
    RepairActionCode,
    RepairActionOut,
    RepairEvidenceOut,
    RepairSignalCode,
    RepairSignalOut,
    RepairSourceOut,
    RepairSuggestionListOut,
    RepairSuggestionOut,
)
from .services import _require_aware_utc

LOOKBACK_DAYS = 30
REPEATED_AGAIN_COUNT = 2
SLOW_HARD_COUNT = 2
SLOW_RESPONSE_MS = 60_000


class RepairSuggestionReferenceError(RuntimeError):
    pass


def _card_tags(card: Card) -> list[str]:
    values = list(card.tags or []) or _legacy_list(card.tags_json)
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _topic(card: Card, tags: list[str], confusion_tags: list[str]) -> str:
    if confusion_tags:
        return confusion_tags[0]
    if tags:
        return tags[0]
    return card.chapter or card.section or card.book.subject or card.book.name


def _source(card: Card) -> RepairSourceOut:
    source = card.sources[0] if card.sources else None
    legacy_pages = [
        int(value)
        for value in _legacy_list(card.source_pages_json)
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    return RepairSourceOut(
        card_id=card.id,
        card_revision=card.content_revision,
        book_id=card.book_id,
        book_name=card.book.name,
        subject=card.book.subject,
        chapter=card.chapter,
        section=card.section,
        source_id=source.id if source else None,
        excerpt=source.excerpt if source else (card.source_excerpt or ""),
        pdf_page_start=(
            source.pdf_page_index_start + 1
            if source
            else (min(legacy_pages) if legacy_pages else None)
        ),
        pdf_page_end=(
            source.pdf_page_index_end + 1
            if source
            else (max(legacy_pages) if legacy_pages else None)
        ),
        printed_page_start_label=source.printed_page_start_label if source else None,
        printed_page_end_label=source.printed_page_end_label if source else None,
    )


def _actions(
    *,
    signals: list[RepairSignalCode],
    issue_types: set[str],
) -> list[RepairActionOut]:
    result: list[RepairActionOut] = []

    def add(code: RepairActionCode, reason: str) -> None:
        if all(item.code != code for item in result):
            result.append(RepairActionOut(code=code, reason=reason))

    if issue_types & {"fact_error", "source_error"}:
        add(RepairActionCode.REVIEW_CONTENT, "verify the card against its cited source")
    if issue_types & {"too_large", "unclear"}:
        add(RepairActionCode.SPLIT_CARD, "split or clarify the card through content review")
    if RepairSignalCode.TAG_CONFUSION in signals or "concept_confusion" in issue_types:
        add(RepairActionCode.COMPARE_CARDS, "compare the related cards under the shared topic")
    if RepairSignalCode.REPEATED_AGAIN in signals:
        add(RepairActionCode.REREAD_SOURCE, "reread the cited passage before another recall")
    if RepairSignalCode.SLOW_HARD in signals:
        add(RepairActionCode.WRITTEN_RECALL, "practice one unhinted written recall")
    if "too_difficult" in issue_types:
        add(RepairActionCode.WRITTEN_RECALL, "practice the difficult card in a slower written mode")
    return result


def _plan_reason(signals: list[RepairSignalCode]) -> str:
    if RepairSignalCode.CARD_ISSUE in signals:
        return "REPAIR_CARD_ISSUE"
    if RepairSignalCode.TAG_CONFUSION in signals:
        return "REPAIR_TAG_CONFUSION"
    if RepairSignalCode.REPEATED_AGAIN in signals:
        return "REPAIR_REPEATED_AGAIN"
    return "WEAK_SLOW_HARD"


def build_repair_suggestions(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
    limit: int = 100,
) -> RepairSuggestionListOut:
    """Build deterministic, read-only repair suggestions from real learning evidence."""
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise RepairSuggestionReferenceError("an active Owner is required")
    timestamp = _require_aware_utc(now or datetime.now(UTC))
    lookback = timestamp - timedelta(days=LOOKBACK_DAYS)
    capped_limit = min(max(limit, 1), 10_000)

    active_card_ids = set(
        db.scalars(
            select(CardEnrollment.card_id).where(
                CardEnrollment.user_id == user_id,
                CardEnrollment.status == "active",
            )
        )
    )
    attempts = list(
        db.scalars(
            select(ReviewAttempt)
            .where(
                ReviewAttempt.user_id == user_id,
                ReviewAttempt.reviewed_at >= lookback,
                ReviewAttempt.card_id.in_(active_card_ids),
            )
            .order_by(ReviewAttempt.reviewed_at.desc(), ReviewAttempt.id.desc())
        )
    )
    issues = list(
        db.scalars(
            select(CardIssue).where(
                CardIssue.user_id == user_id,
                CardIssue.status.in_(("open", "in_review")),
                CardIssue.card_id.in_(active_card_ids),
            )
        )
    )
    candidate_ids = {attempt.card_id for attempt in attempts} | {issue.card_id for issue in issues}
    if not candidate_ids:
        return RepairSuggestionListOut(
            user_id=user_id,
            lookback_days=LOOKBACK_DAYS,
            generated_at=timestamp,
            items=[],
        )

    cards = list(
        db.scalars(
            select(Card)
            .options(joinedload(Card.book), selectinload(Card.sources))
            .where(Card.id.in_(candidate_ids), Card.status == "published")
        )
    )
    cards_by_id = {card.id: card for card in cards}
    attempts_by_card: dict[int, list[ReviewAttempt]] = defaultdict(list)
    issues_by_card: dict[int, list[CardIssue]] = defaultdict(list)
    for attempt in attempts:
        if attempt.card_id in cards_by_id:
            attempts_by_card[attempt.card_id].append(attempt)
    for issue in issues:
        if issue.card_id in cards_by_id:
            issues_by_card[issue.card_id].append(issue)

    low_card_ids_by_tag: dict[str, set[int]] = defaultdict(set)
    for card_id, rows in attempts_by_card.items():
        if any(row.rating <= 2 for row in rows):
            for tag in _card_tags(cards_by_id[card_id]):
                low_card_ids_by_tag[tag].add(card_id)

    suggestions: list[RepairSuggestionOut] = []
    for card_id, card in cards_by_id.items():
        rows = attempts_by_card[card_id]
        card_issues = issues_by_card[card_id]
        tags = _card_tags(card)
        again_count = sum(row.rating == 1 for row in rows)
        hard_count = sum(row.rating == 2 for row in rows)
        slow_hard_count = sum(
            row.rating == 2 and row.response_ms >= SLOW_RESPONSE_MS for row in rows
        )
        confusion_tags = sorted(tag for tag in tags if len(low_card_ids_by_tag[tag]) >= 2)
        related_card_ids = sorted(
            {
                related_id
                for tag in confusion_tags
                for related_id in low_card_ids_by_tag[tag]
                if related_id != card_id
            }
        )
        issue_types = {issue.issue_type for issue in card_issues}
        signal_codes: list[RepairSignalCode] = []
        signal_rows: list[RepairSignalOut] = []
        if again_count >= REPEATED_AGAIN_COUNT:
            signal_codes.append(RepairSignalCode.REPEATED_AGAIN)
            signal_rows.append(
                RepairSignalOut(
                    code=RepairSignalCode.REPEATED_AGAIN,
                    detail=f"again_count={again_count};lookback_days={LOOKBACK_DAYS}",
                )
            )
        if slow_hard_count >= SLOW_HARD_COUNT:
            signal_codes.append(RepairSignalCode.SLOW_HARD)
            signal_rows.append(
                RepairSignalOut(
                    code=RepairSignalCode.SLOW_HARD,
                    detail=(f"slow_hard_count={slow_hard_count};threshold_ms={SLOW_RESPONSE_MS}"),
                )
            )
        if confusion_tags:
            signal_codes.append(RepairSignalCode.TAG_CONFUSION)
            signal_rows.append(
                RepairSignalOut(
                    code=RepairSignalCode.TAG_CONFUSION,
                    detail=(
                        f"tags={','.join(confusion_tags)};"
                        f"related_card_ids={','.join(map(str, related_card_ids))}"
                    ),
                )
            )
        if issue_types:
            signal_codes.append(RepairSignalCode.CARD_ISSUE)
            signal_rows.append(
                RepairSignalOut(
                    code=RepairSignalCode.CARD_ISSUE,
                    detail=f"open_issue_types={','.join(sorted(issue_types))}",
                )
            )
        if not signal_codes:
            continue

        latest_failure = max(
            (row.reviewed_at for row in rows if row.rating <= 2),
            default=None,
        )
        severity = (
            again_count * 3
            + slow_hard_count * 2
            + len(confusion_tags) * 4
            + len(issue_types) * 2
            + (5 if issue_types & {"fact_error", "source_error"} else 0)
        )
        reason_code = _plan_reason(signal_codes)
        actions = _actions(signals=signal_codes, issue_types=issue_types)
        suggestions.append(
            RepairSuggestionOut(
                card_id=card.id,
                card_revision=card.content_revision,
                topic=_topic(card, tags, confusion_tags),
                tags=tags,
                severity_score=severity,
                reason_code=reason_code,
                reason_detail=(
                    f"signals={','.join(code.value for code in signal_codes)};"
                    f"actions={','.join(action.code.value for action in actions)}"
                ),
                signals=signal_rows,
                actions=actions,
                evidence=RepairEvidenceOut(
                    attempt_count=len(rows),
                    again_count=again_count,
                    hard_count=hard_count,
                    slow_hard_count=slow_hard_count,
                    issue_types=[CardIssueType(value) for value in sorted(issue_types)],
                    confusion_tags=confusion_tags,
                    related_card_ids=related_card_ids,
                    latest_failure_at=latest_failure,
                ),
                source=_source(card),
            )
        )

    suggestions.sort(
        key=lambda item: (
            -item.severity_score,
            -(item.evidence.latest_failure_at or lookback).timestamp(),
            item.card_id,
        )
    )
    return RepairSuggestionListOut(
        user_id=user_id,
        lookback_days=LOOKBACK_DAYS,
        generated_at=timestamp,
        items=suggestions[:capped_limit],
    )
