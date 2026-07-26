# P6-T06 Weak Topic and Repair Rules

- Status: complete
- Generated: 2026-07-26
- Tracked: deterministic repair signals, concrete actions, source attribution, DailyPlan integration, read-only API, and acceptance fixtures.

## Rules

| Signal | Threshold | Plan reason |
|---|---|---|
| Repeated Again | at least 2 in 30 days | `REPAIR_REPEATED_AGAIN` |
| Slow sustained Hard | at least 2 Hard responses, each at least 60 seconds | `WEAK_SLOW_HARD` |
| Tag confusion | at least 2 active cards under the same tag have recent Again/Hard | `REPAIR_TAG_CONFUSION` |
| Card Issue | open/in_review issue, aggregated by card and type | `REPAIR_CARD_ISSUE` |

Resolved/dismissed Issues, one Again, fast Hard responses, and a failed card with no second failed card under the same tag do not trigger suggestions.

## Output Contract

Each suggestion contains:

- exact card id and content revision;
- topic, tags, severity, stable reason code/detail;
- structured signal evidence and one or more concrete actions;
- related card ids for confusion comparisons;
- book, subject, chapter, section, source id, excerpt, PDF pages, and printed page labels.

Structured CardSource is preferred. Legacy cards fall back to `source_excerpt` and `source_pages_json`.

## Actions

- `reread_source`: return to the cited passage after repeated forgetting.
- `written_recall`: perform one unhinted written recall for slow Hard behavior.
- `compare_cards`: compare related cards under a shared confused tag.
- `split_card`: send oversized/unclear content through review for decomposition.
- `review_content`: verify fact/source issues against the citation.

The service is read-only. It does not create CandidateCard rows, rewrite published cards, or auto-publish generated repairs.

## HTTP API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/learning/repair-suggestions` | Owner-scoped, stable severity ordering, `limit` 1-500 |

## DailyPlan

`_build_weak_candidates` consumes `build_repair_suggestions`, so plan items and the repair detail view use the same thresholds, reason codes, and actions. Due items still retain priority because DailyPlan excludes already-selected due cards before adding repair candidates.

## Verification

- repair rules + DailyPlan focused pytest: **11 passed**
- P6-T03 through P6-T06 focused pytest: **24 passed, 2 skipped**
- full server pytest: **149 passed, 3 skipped**
- ruff on touched files: passed
- `git diff --check`: passed

## Remaining Risks

- Thresholds are deterministic v1 constants; tuning requires real longitudinal data and should version the rule set.
- Tag confusion depends on catalog tag quality and currently treats two recent low-rated cards under one tag as sufficient evidence.
- P6-T07 will build paginated weak-topic/insight read models on this service.
- PostgreSQL concurrency/migration markers still require `WXZY_TEST_POSTGRES_URL`.
