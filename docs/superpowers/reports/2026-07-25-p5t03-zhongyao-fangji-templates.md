# P5-T03 中药/方剂模板

- Status: complete
- Generated: 2026-07-25T03:19:45.506364+00:00
- Tracked: templates/rules/fixtures + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| zhongyao templates (nature/function/indication/usage/toxicity/compat/contrast) | True (herb_compatibility, herb_contrast, herb_function, herb_indication, herb_nature_flavor, herb_toxicity_caution, herb_usage; n=13) |
| fangji templates (compose/function/indication/song/usage/compat) | True (formula_compatibility, formula_compose, formula_function, formula_indication, formula_song, formula_usage_note; n=11) |
| Dosage / toxicity high-critical flags | True |
| All golden cards pass v2 gate | True |
| Structure fixtures still extract basic cards | True |

## Artifacts

- `tools/document_pipeline/templates_zhongyao_fangji.py`
- `tools/document_pipeline/fixtures/templates_zhongyao_golden.md`
- `tools/document_pipeline/fixtures/templates_fangji_golden.md`
- `tools/tests/test_templates_zhongyao_fangji.py`
- risk defaults extended in `tools/document_pipeline/candidate_schema.py`

## Card types / risk

| Type | Risk | Flags |
|---|---|---|
| herb_nature_flavor | medium | herb_nature_flavor |
| herb_function | medium | herb_function |
| herb_indication | medium | herb_indication |
| herb_usage | high | dosage_or_usage |
| herb_toxicity_caution | critical | toxicity_or_contraindication |
| herb_compatibility | medium | herb_compatibility |
| herb_contrast | medium | herb_contrast |
| formula_compose | high | dosage_or_compose |
| formula_function | medium | formula_function |
| formula_indication | medium | formula_indication |
| formula_song | high | formula_song |
| formula_usage_note | high | usage_or_caution |
| formula_compatibility | medium | formula_compatibility |

## Notes

- Deterministic section/table parsing; no LLM required for golden path.
- Representative chapters use short fixtures; local full cleaned text stays in `data/`.
- Emitted cards are Candidate Card v2 and remain candidates only.
- Herb multi-col inventory tables are preferred over contrast classification when both heuristics could match.

## Verification

- pytest: `tools/tests/test_templates_zhongyao_fangji.py + test_templates_jichu_zhenduan.py + test_candidate_schema_v2.py + test_generate_candidate_cards.py => 34 passed`
- ruff/mypy: clean on new/changed modules
