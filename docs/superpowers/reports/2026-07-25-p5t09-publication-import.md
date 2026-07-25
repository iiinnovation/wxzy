# P5-T09 Publication Import API

- Status: complete
- Generated: 2026-07-25T05:59:25+00:00
- Tracked: validate/import/status API + idempotent import records + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| validate/import/status endpoints | True (`/api/v1/admin/publications/*`) |
| Transactional import | True (conflict paths roll back) |
| publication_id + hash idempotency | True (identical re-import replays stored result) |
| same publication_id different hash conflict | True (no overwrite) |
| card content_hash conflict | True (no partial write / no import record) |
| Import does not create ReviewState/CardReviewState | True |
| Catalog grows, due does not | True |

## Artifacts

- `server/app/publishing/models.py`
- `server/app/publishing/schemas.py`
- `server/app/publishing/services.py`
- `server/app/routers/admin.py`
- `server/migrations/versions/20260725_0008_publication_imports.py`
- `server/tests/test_publication_import.py`
- `server/tests/test_migrations.py` (head revision `20260725_0008`)

## API contract

```text
POST /api/v1/admin/publications/validate
POST /api/v1/admin/publications/import
GET  /api/v1/admin/publications/{publication_id}
```

Rules:
- package checksum/manifest validation first
- same publication_id + matching hashes => idempotent replay
- same publication_id + different hashes => conflict, keep original record
- same card external_id + different content_hash => conflict, full rollback
- published cards only; no ReviewState / CardReviewState creation

## Verification

- pytest: `server/tests/test_publication_import.py` => 8 passed
- pytest: migration head/legacy upgrade => passed (`20260725_0008`, `publication_imports`)
- related: `tools/tests/test_publication_export.py` included in focused suite
- stage: `publication_import` / `p5t09-v1`
