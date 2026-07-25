# P6-T02 Enrollment Service

- Status: complete
- Generated: 2026-07-25T07:25:57.164735+00:00
- Tracked: book/chapter/card enrollment service + HTTP API + acceptance tests + this report.

## Acceptance

| Check | Result |
|---|---|
| Enroll by book / chapter / card | True |
| Lifecycle queued/active/suspended/retired | True |
| Chapter introduction order | True |
| Idempotent re-enroll | True |
| Chapter join does not bulk-create due | True |
| Suspend excludes from due, history kept | True |

## Service API

```text
enroll_card / enroll_chapter / enroll_book / enroll_scope
list_enrollable_card_ids_for_chapter / list_enrollable_card_ids_for_book
list_queued_enrollments  # priority DESC, chapter order, card id
introduce_enrollment / change_enrollment_status / list_due_review_states
```

Rules:
- enroll creates only `queued` rows; never creates `CardReviewState`
- chapter enroll includes chapter subtree via `parent_id`
- book/chapter source = `chapter`; single card source = `manual`
- re-enroll returns existing row without status rewrite
- only `approved` / `published` cards are enrollable

## HTTP API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/enrollments` | body: scope + card_id/chapter_id/book_id |
| PATCH | `/api/v1/enrollments/{id}` | body: status active/suspended/retired |

## Artifacts

- `server/app/learning/schemas.py`
- `server/app/learning/services.py`
- `server/app/api/v1/enrollments.py`
- `server/app/api/v1/router.py`
- `server/tests/test_learning.py`
- `server/tests/test_enrollments_api.py`

## Verification

- pytest focused suite => **39 passed, 2 skipped**
  - `server/tests/test_learning.py`
  - `server/tests/test_enrollments_api.py`
  - `server/tests/test_review_attempts.py`
  - `server/tests/test_domain_services.py`
  - `server/tests/test_api_v1.py`
  - `server/tests/test_catalog.py`
- ruff on touched files => passed
- stage: `enrollment_service` / `p6t02-v1`
