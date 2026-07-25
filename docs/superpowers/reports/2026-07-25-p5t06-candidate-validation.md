# P5-T06 自动卡片校验与去重

- Status: complete
- Generated: 2026-07-25T03:40:00.677116+00:00
- Tracked: validator/fixtures/tests + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| schema / provenance / risk gate | True (via validate_candidate_card_v2) |
| fabricated dosage intercepted | True (`fabricated_dosage`) |
| no-source answer intercepted | True (`source_coverage_fail`) |
| duplicate / near-duplicate intercepted | True (`near_duplicate`) |
| multi-version mix intercepted | True (`multi_version_mix`) |
| min knowledge point / length checks | True (`missing_min_knowledge_point`) |
| clean controls accepted | True (白虎汤功用 + 十版中风分类) |
| output remains candidate-only | True |

## Artifacts

- `tools/document_pipeline/candidate_validation.py`
- `tools/document_pipeline/fixtures/validation_p5t06_cards.json`
- `tools/tests/test_candidate_validation.py`

## Checks implemented

- schema_gate
- question/answer length bounds
- missing_min_knowledge_point
- source_coverage_fail
- fabricated_dosage
- fabricated_entity (high/critical conservative)
- multi_version_mix / missing_version_cue
- near_duplicate (exact content_hash + question/answer similarity)

## Fixture evidence

- accepted: ['baihu-function-control', 'single-version-zhongfeng-10']
- rejected codes:
  - `fake-dose-guizhi-compose`: fabricated_dosage, source_coverage_fail
  - `no-source-answer`: fabricated_dosage, fabricated_entity, source_coverage_fail
  - `dup-a-mahuang-compose`: near_duplicate
  - `dup-b-mahuang-compose`: near_duplicate
  - `multi-version-zhongfeng`: fabricated_entity, multi_version_mix, source_coverage_fail
  - `long-answer-no-points`: missing_min_knowledge_point

## Verification

- pytest: `tools/tests/test_candidate_validation.py` => 9 passed
- related suite (schema/templates/cursor/validation/generate) => 62 passed
- ruff/mypy: clean on `candidate_validation.py`
- stage: `candidate_validation` / `p5t06-v1`
