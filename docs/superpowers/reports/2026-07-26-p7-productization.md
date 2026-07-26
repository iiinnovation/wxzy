# P7 小程序产品化验收

- Status: implementation complete; external runtime acceptance blocked
- Generated: 2026-07-26
- Completed: P7-T01 through P7-T08
- Blocked: P7-T09 Developer Tools and real-device acceptance

## Delivered Scope

| Task | Result | Evidence |
|---|---|---|
| P7-T01 API clients | Complete | split clients, centralized auth/error/timeout/request ID, Node fixtures |
| P7-T02 Onboarding | Complete | goal, optional date, budget, study days, priorities, save/recovery |
| P7-T03 Today | Complete | DailyPlan summary, preview, adjustment, full request states |
| P7-T04 Study session | Complete | cursor session, recall/reveal/source/rating, idempotent retry, interrupt/resume |
| P7-T05 Catalog | Complete | 7-book catalog, chapters, paginated cards, join/pause/resume |
| P7-T06 Insights | Complete | summary, workload, trends, weak topics, mixed weekly test |
| P7-T07 Me | Complete | profile, sessions, export/delete, production-hidden dev token |
| P7-T08 Components | Complete | state, progress, rating, source and plan summary components |
| P7-T09 Runtime | Blocked | IDE initialization fails before project compilation; no real-device evidence |

## Review Fixes

- Owner deletion explicitly removes all learning rows, independent of SQLite cascade behavior.
- Owner export includes learning-profile audit history and excludes authentication secrets.
- Interrupted sessions return no task, and resume continues from the same pending plan item.
- Rating retries retain the original payload and `client_attempt_id`; another rating cannot be selected.
- Source loading exposes errors and retry, and nested WXML components are dependency-checked.
- Budget adjustment preserves completed history and unfinished plan items and synchronizes session totals.
- Weekly mixed attempts do not change FSRS state or due dates.
- First-publication output uses an explicit timestamp and reproducible package hashes.

## Real Database Acceptance

The stable first-publication package was imported into the real database after backup.

| Check | Result |
|---|---:|
| Books visible | 7 |
| Chapters visible | 19 |
| Published cards | 71 |
| Source coverage | 100% |
| High/critical review coverage | 100% |
| ReviewState created by import | 0 |
| CardReviewState created by import | 0 |
| Due before and after import | 15 -> 15 |
| Idempotent replay | true |

Stable publication identifiers:

- publication: `pub-first-batch-p5t10-v1`
- manifest hash: `b932139200afd5c87426e0ae56d40ef99a4049e53dd452a408204081e9dd7908`
- package hash: `d3c1b92544c16f36624352c1a1793640189293896451247060d275b52b783162`

Backups:

- `server/backups/wxzy-before-p7-first-publication-20260726.db`
- SHA-256: `bf75e901c70158640851be50f5ac15971868e08a9b8f57917a465e1231d9ae05`
- pre-migration backup: `server/backups/wxzy-before-20260726-p7.db`
- SHA-256: `41a8eb74f5484f370d9ed5c9f0483002eff5aa428fd5e520c59c065688dd1d34`

## HTTP Smoke

Read-only smoke against `http://127.0.0.1:8000` after the final import returned:

- 7 books, 19 chapters and 71 published cards.
- DailyPlan: 15 items, all 15 pending; 15 due, 0 new and 0 weak.
- Legacy-compatible stats: 78 learnable cards and 15 due now.
- `/health`: HTTP 200 with a request ID.

No token or personal export content was printed by the smoke.

## Verification

- unified quality gate: **316 passed, 3 skipped**, 75% coverage, PASS
- mypy: no issues in 125 files
- Ruff lint and format: passed
- JavaScript syntax: 37 files passed
- strict JSON: 22 files passed
- documentation checks: 40 files passed
- Alembic real database/head: `20260725_0010`
- `alembic check`: no schema drift

The three skipped cases require PostgreSQL (`WXZY_TEST_POSTGRES_URL`) or avoid the Python 3.14 shared-memory SQLite concurrency segfault. They do not substitute for the deferred PostgreSQL checks in P8.

## P7-T09 Blocker

After terminating the failed IDE processes, this clean retry was run:

```text
/Applications/wechatwebdevtools.app/Contents/MacOS/cli open \
  --project /Users/apple/Desktop/wxzy --port 9420 --lang zh --disable-gpu
```

It failed with:

```text
#initialize-error: wait IDE port timeout
```

Port 9420 did not listen. The latest log is:

```text
/Users/apple/Library/Application Support/微信开发者工具/50a7d9210159a32f006158795f893857/WeappLog/logs/2026-07-26-12-33-55-991-CnqGAiiHGY.log
```

The log reports `devtools manifest.json ... not installed`, `version manifest.json ... not installed`, and `doCheckUpdate -80150`. This happens before project compilation, so it is not evidence of a project compile failure or success.

Developer Tools compilation, simulator network checks, performance panel, minimum base-library validation and all 10 real-device PRD scenarios remain unverified. P7 cannot pass its final exit gate until that external environment works.

## Remaining Work

- P7-T09: 1 blocked task.
- P8: 7 deferred deployment and stability tasks.
- P9: 6 deferred two-week usage and calibration tasks.
- Total incomplete tasks after this report: **14**.
