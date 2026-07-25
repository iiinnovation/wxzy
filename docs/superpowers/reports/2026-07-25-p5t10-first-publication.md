# P5-T10 首批正式发布

- Status: complete
- Generated: 2026-07-25T06:45:33.580404+00:00
- Tracked: first formal 7-book publication pipeline + catalog visibility for published cards + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| 7 books visible in catalog | True |
| All published cards have sources 100% | True |
| High/critical review coverage 100% | True |
| Catalog lists approved + published | True |
| Import does not create ReviewState/CardReviewState | True |
| due unchanged after import | True |
| Identical package re-import is idempotent | True |

## Batch summary

- publication_id: `pub-first-batch-p5t10-v1`
- cards: **71**
- books: **7**
- source_coverage: **1.0**
- high_risk_review_coverage: **1.0**
- manifest_hash: `666d9f22e815c140f34cdb0e24184966e926371bbd21d041c36655c332affb76`
- package_hash: `11d7d12be442b9b6c0806763a301ca2343868d0b5f173afa1a483ae8ae7fb82b`

| Book | Key | Cards | Chapters | High/Critical | Reviewed | With sources |
|---|---|---:|---:|---:|---:|---:|
| 方剂学 | fangji | 11 | 1 | 6 | 6 | 11 |
| 中医基础理论 | jichu | 8 | 1 | 0 | 0 | 8 |
| 中医内科学 | neike | 9 | 4 | 6 | 6 | 9 |
| 人文 | renwen | 9 | 3 | 3 | 3 | 9 |
| 中医诊断学 | zhenduan | 11 | 3 | 5 | 5 | 11 |
| 针灸学 | zhenjiu | 10 | 4 | 6 | 6 | 10 |
| 中药学 | zhongyao | 13 | 3 | 5 | 5 | 13 |

## Pipeline

```text
golden fixtures
  -> extract_first_batch_candidates
  -> review_first_batch (chapter batch + one-by-one high/critical)
  -> export_publication
  -> import_publication_package
  -> catalog visibility (approved + published)
```

Rules:
- every book reviews at least one chapter
- high/critical cards require explicit one-by-one approve with reviewer + reviewed_at
- package export gates stay candidate-approved only; import materializes `published`
- catalog default status filter is `approved|published` (`status=catalog|visible|omit`)
- import must not create learning due / ReviewState / CardReviewState

## Artifacts

- `tools/document_pipeline/first_publication.py`
- `tools/tests/test_first_publication.py`
- `server/tests/test_first_publication_import.py`
- `server/app/catalog/services.py`
- `server/app/routers/cards.py`

## Verification

- pytest focused suite => **26 passed**
  - `tools/tests/test_first_publication.py`
  - `server/tests/test_first_publication_import.py`
  - `tools/tests/test_publication_export.py`
  - `server/tests/test_publication_import.py`
  - `server/tests/test_domain_services.py`
- ruff on touched files => passed
- stage: `first_publication` / `p5t10-v1`
