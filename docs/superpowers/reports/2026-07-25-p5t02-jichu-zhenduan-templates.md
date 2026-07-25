# P5-T02 基础理论/诊断模板

- Status: complete
- Generated: 2026-07-25T02:18:37+00:00
- Tracked: templates/rules/fixtures + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| jichu templates (definition/mechanism/relation/contrast) | True (concept_definition, contrast, mechanism, relation; n=8) |
| zhenduan templates (four_exam/symptom_syndrome/syndrome/differential) | True (differential, four_exam, symptom_syndrome, syndrome; n=11) |
| All golden cards pass v2 gate | True |
| Structure fixtures still extract basic cards | True |

## Artifacts

- `tools/document_pipeline/templates_jichu_zhenduan.py`
- `tools/document_pipeline/fixtures/templates_jichu_golden.md`
- `tools/document_pipeline/fixtures/templates_zhenduan_golden.md`
- `tools/tests/test_templates_jichu_zhenduan.py`
- risk defaults extended in `tools/document_pipeline/candidate_schema.py`

## Card types / risk

| Type | Risk | Flags |
|---|---|---|
| concept_definition | low | — |
| mechanism | medium | pathogenesis_summary |
| relation | medium | relation_summary |
| contrast | medium | contrast_pair |
| four_exam | low | — |
| symptom_syndrome | medium | symptom_mapping |
| syndrome | high | syndrome_mapping |
| differential | high | differential_diagnosis |

## Notes

- Deterministic section/table parsing; no LLM required for golden path.
- Representative chapters use short fixtures; local full cleaned text stays in `data/`.
- Emitted cards are Candidate Card v2 and remain candidates only.

## Verification

- pytest: `tools/tests/test_templates_jichu_zhenduan.py + test_candidate_schema_v2.py + test_generate_candidate_cards.py => 22 passed`
- ruff/mypy: clean on new/changed modules
