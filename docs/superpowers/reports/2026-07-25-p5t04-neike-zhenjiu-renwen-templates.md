# P5-T04 内科/针灸/人文模板

- Status: complete
- Generated: 2026-07-25T03:25:30.228061+00:00
- Tracked: templates/rules/fixtures + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| neike templates (concept/pathogenesis/principle/syndrome/versioned) | True (disease_concept, disease_pathogenesis, syndrome_formula, treatment_principle, versioned_classification; n=10) |
| zhenjiu templates (meridian/location/indication/operation/caution) | True (acupoint_caution, acupoint_indication, acupoint_location, acupoint_operation, meridian_overview; n=10) |
| renwen templates (ethics/regulation/scenario) | True (ethics_principle, ethics_scenario, regulation_fact; n=10) |
| Version fields + risk rules | True |
| All golden cards pass v2 gate | True |
| Structure fixtures still extract basic cards | True |

## Artifacts

- `tools/document_pipeline/templates_neike_zhenjiu_renwen.py`
- `tools/document_pipeline/fixtures/templates_neike_golden.md`
- `tools/document_pipeline/fixtures/templates_zhenjiu_golden.md`
- `tools/document_pipeline/fixtures/templates_renwen_golden.md`
- `tools/tests/test_templates_neike_zhenjiu_renwen.py`
- risk defaults extended in `tools/document_pipeline/candidate_schema.py`

## Card types / risk

| Type | Risk | Flags |
|---|---|---|
| disease_concept | low | — |
| disease_pathogenesis | medium | pathogenesis_summary |
| treatment_principle | medium | treatment_principle |
| syndrome_formula | high | syndrome_formula |
| versioned_classification | critical | multi_version |
| meridian_overview | low | — |
| acupoint_location | high | acupoint_location |
| acupoint_indication | medium | acupoint_indication |
| acupoint_operation | high | needling_depth_or_direction |
| acupoint_caution | critical | needling_contraindication |
| ethics_principle | medium | ethics_principle |
| regulation_fact | high | regulation_or_statute |
| ethics_scenario | high | ethics_scenario |
| history_fact | low | — |

## Notes

- Deterministic section/table parsing; no LLM required for golden path.
- Representative chapters use short fixtures; local full cleaned text stays in `data/`.
- Multi-version classification and dated regulations keep explicit version cues and elevated risk.
- Emitted cards are Candidate Card v2 and remain candidates only.

## Verification

- pytest: `tools/tests/test_templates_neike_zhenjiu_renwen.py + test_templates_zhongyao_fangji.py + test_templates_jichu_zhenduan.py + test_candidate_schema_v2.py + test_generate_candidate_cards.py => 47 passed`
- ruff/mypy: clean on new/changed modules
