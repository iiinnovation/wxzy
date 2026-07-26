# 整体代码审查与修复

- Status: code findings fixed; external runtime checks remain tracked separately
- Generated: 2026-07-26
- Scope: backend identity/catalog/learning/publishing, migrations, document publication controls, miniprogram services/pages/components, and repository quality gates

## Findings Fixed

| Severity | Finding | Fix and evidence |
|---|---|---|
| High | Authentication opens a SQLite read transaction before review writes, bypassing `BEGIN IMMEDIATE`; concurrent idempotent writes could return lock errors or race FSRS state. | All SQLite review, enrollment, introduction, plan-session and publication-import boundaries now reserve the single writer before replay lookup. File-backed two-thread review and publication tests pass. |
| High | A matching card content hash caused publication import to skip an approved or source-less card, leaving it non-published or without citations. | Import skips only a complete published card; otherwise it materializes publication metadata and sources. Regression verifies approved -> published and source repair. |
| Medium | Parent chapters without direct cards disappeared from the catalog; parent counts, card search and subtree enrollment described different scopes. | Catalog includes ancestor chapters, aggregates deduplicated subtree counts, and parent search traverses the same subtree used by enrollment. |
| Medium | Publication validation accepted zero count mismatches, could throw on nonnumeric counts, and ignored disagreement between manifest and checksum sidecar metadata. | Counts are required non-negative integers and must equal observed rows. File maps, publication ID, package hash and manifest hash must agree across both files. |
| Medium | Publication packages allowed missing/duplicate card IDs and duplicate source order/chunk identities until database failure. | Stable identities and source uniqueness are rejected during validation with deterministic errors. |
| Medium | A non-retriable rating conflict was presented as an idempotent retry, permanently locking the stale card UI. | Only explicit retriable errors retain the original payload; conflicts require reloading server progress and do not allow rating changes. |
| Medium | Leaving Study Session via system navigation kept the server session active and could inflate elapsed minutes. | Page unload performs a best-effort interrupt; an in-flight successful rating is interrupted immediately after its transaction completes. |
| Medium | Legacy `review/library` prototype pages and root `/review` wrappers remained in the production miniprogram package. | Prototype pages were removed from `app.json`; reachable learning clients now use split `/api/v1` services only. |
| Low | Owner export omitted the active timing cursor needed to restore an in-progress session. | `active_started_at` is exported and covered by an active-session API test; authentication secrets remain excluded. |
| Low | An unenrolled card displayed mastery as “学习中”. | Card detail now distinguishes “未开始”, “学习中” and “已达到”. |

## Verification

- Unified gate: **316 passed, 3 skipped**, 75% coverage, PASS.
- Mypy: no issues in 125 source files.
- Ruff lint and format: passed across `server/` and `tools/`.
- Miniprogram JavaScript syntax: 37 files passed.
- Structured JSON: 22 files passed.
- Documentation: 40 files passed.
- Alembic real database/head: `20260725_0010`; `alembic check` reports no drift.
- Stable publication package validates with 7 documents, 19 chapters, 66 chunks, 71 cards and 71 card sources.
- Restarted runtime smoke: 7 books, 19 chapters, 71 published cards, 15/15 DailyPlan items pending, 78 learnable cards and 15 due.

## Skips And External Evidence

The three skips are explicit:

- PostgreSQL migration check requires `WXZY_TEST_POSTGRES_URL`.
- PostgreSQL concurrent review check requires the same variable.
- Python 3.14 shared-memory SQLite thread test is skipped because it can segfault; a file-backed SQLite concurrency test now runs instead.

P7-T09 remains blocked before project compilation by WeChat Developer Tools plugin initialization (`manifest.json not installed`, `doCheckUpdate -80150`, port 9420 timeout). Developer Tools, minimum base-library and real-device acceptance are not represented as passed by this review.

## Runtime

The reviewed code is running at `http://127.0.0.1:8000` after restart. The read-only smoke did not print credentials or personal export content.
