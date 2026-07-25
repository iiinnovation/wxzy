# P5-T01 Candidate Card v2 Schema

- Status: complete
- Generated: 2026-07-25T02:08:05.041050+00:00
- Tracked: schema/rules/fixtures + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| Convert 18 offline v1 samples | True (18/18) |
| Gate fails without provenance | True (18/18) |
| Gate fails high-risk without flags | True |
| Enriched sample passes gate | True |

## Artifacts

- `tools/document_pipeline/schemas/candidate_card.v2.schema.json`
- `tools/document_pipeline/schemas/candidate_card.v1.schema.json`
- `tools/document_pipeline/candidate_schema.py`
- `tools/tests/test_candidate_schema_v2.py`

## Fields added

- `schema_version=2`
- `document_key`
- `document_version`
- `chunk_ids`
- `sources`
- `pdf_page_indexes`
- `printed_page_labels`
- `risk_level`
- `risk_flags`
- `content_hash`
- `generator`
- `model`
- `prompt_version`
- `generation_batch_id`
- `input_hash`
- `reviewer`
- `reviewed_at`
- `review_notes`
- `review_decision`

## Notes

- Legacy offline samples convert without page/chunk provenance; gate requires provenance before review/publish.
- High/critical risk requires non-empty risk_flags.
- Tracked schema lives under tools/document_pipeline/schemas; data/ remains gitignored.

## Verification

- pytest: `tools/tests/test_candidate_schema_v2.py + tools/tests/test_generate_candidate_cards.py => 9 passed`
- ruff: `candidate_schema.py / test_candidate_schema_v2.py clean`
