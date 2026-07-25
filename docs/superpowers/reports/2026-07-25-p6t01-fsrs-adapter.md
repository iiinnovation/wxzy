# P6-T01 标准 FSRS Adapter

- Status: complete
- Generated: 2026-07-25T06:52:35.163723+00:00
- Tracked: standard py-fsrs adapter + dry-run upgrade report + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| Four ratings produce distinct due | True |
| All due timestamps are UTC-aware | True |
| Algorithm upgrade dry-run (no write) | True |
| No new business code imports `fsrs_simple` | True |

## Adapter

- library: `fsrs` (py-fsrs) **6.3.1**
- algorithm_version: `fsrs-6.3.1`
- desired_retention: **0.90**
- enable_fuzzing default: **False** (deterministic schedules/tests)
- ratings: 1=Again, 2=Hard, 3=Good, 4=Easy
- legacy `fsrs_simple` kept only for historical tests; business paths use `app.learning.fsrs_adapter`

## Public API

```text
schedule(...) -> ScheduleResult
dry_run_algorithm_upgrade(rows, ...) -> UpgradeDryRunReport  # applied=False always
utcnow()
ALGORITHM_VERSION / DEFAULT_CONFIG
```

Rules:
- timezone-aware UTC required for `now` / `last_reviewed_at` / `due_at`
- first review of `state=new` leaves S/D unset so FSRS applies initial values
- dry-run never mutates due/algorithm_version rows
- config default `algorithm_version` is now `fsrs-6.3.1`

## Artifacts

- `server/app/learning/fsrs_adapter.py`
- `server/tests/test_fsrs_adapter.py`
- `server/app/learning/services.py` (schedule via adapter)
- `server/app/publishing/services.py` (utcnow via adapter)
- `server/app/config.py`
- `server/requirements.txt` (`fsrs>=6.3,<7.0`)

## Verification

- pytest focused suite => **48 passed, 2 skipped**
  - `server/tests/test_fsrs_adapter.py`
  - `server/tests/test_fsrs_simple.py`
  - `server/tests/test_learning.py`
  - `server/tests/test_review_attempts.py`
  - `server/tests/test_domain_services.py`
  - `server/tests/test_publication_import.py`
- ruff on touched files => passed
- stage: `fsrs_adapter` / `p6t01-v1`
