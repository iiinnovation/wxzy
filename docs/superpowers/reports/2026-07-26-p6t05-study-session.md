# P6-T05 StudySession API

- Status: complete
- Generated: 2026-07-26
- Tracked: DailyPlan-bound session cursor, lifecycle HTTP API, review-attempt advancement, migration, and acceptance tests.

## Acceptance

| Check | Result |
|---|---|
| One current/next task at a time | True |
| Out-of-order card attempt rejected | True |
| Attempt replay does not advance cursor twice | True |
| Interrupt preserves cursor and actual minutes | True |
| Cross-day resume stays on original plan_date | True |
| Empty plan returns task=null and completes | True |
| Completed plan reopen returns original completed session | True |

## HTTP API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/study-sessions` | Pass `daily_plan_id` to create/start or idempotently return the plan session |
| GET | `/api/v1/study-sessions/{id}/next` | Return session plus only the current task, card revision, and review state |
| POST | `/api/v1/study-sessions/{id}/complete` | Complete only after no pending plan item remains |
| POST | `/api/v1/study-sessions/{id}/interrupt` | Persist reason, cursor, and accumulated active minutes |
| POST | `/api/v1/study-sessions/{id}/resume` | Resume the same plan, including across a local-date boundary |

## Transaction Invariant

For a plan-bound session, `submit_review_attempt` locks the session/current plan item and accepts only that card. The first successful request writes the attempt, advances FSRS state, marks the `DailyPlanItem` completed, increments session completion count, and advances the cursor in one commit. An idempotent replay returns before these mutations.

## Migration

- revision: `20260725_0010` (down_revision `20260725_0009`)
- columns: `daily_plan_id`, `plan_date`, `cursor_position`, `active_started_at`
- constraints: one StudySession per non-null DailyPlan; cursor is non-negative
- indexes: `daily_plan_id`, `(user_id, plan_date)`

## Verification

- P6-T03/T04/T05 focused pytest: **22 passed, 2 skipped**
- migration + P6-T05 pytest: **7 passed, 1 skipped**
- full server pytest: **147 passed, 3 skipped**
- ruff on P6-T05 touched files: passed
- `git diff --check`: passed

## Remaining Risks

- PostgreSQL migration and concurrent-attempt markers require `WXZY_TEST_POSTGRES_URL` and were skipped.
- Full-tree ruff is currently blocked by pre-existing import-order/unused-import findings in three unrelated test files; all P6-T05 touched files pass.
- The legacy unbound StudySession create path remains for P6-T03 compatibility; plan cursor behavior is enabled explicitly with `daily_plan_id`.
