# P5-T05 Qwen 全量游标生成器

- Status: complete
- Generated: 2026-07-25T03:33:30.597287+00:00
- Tracked: generator/fixtures/tests + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| ContentBlock cursor, not `md[:max_chars]` | True |
| Input > max_chars covers every chunk | True (zhongyao 22/22 blocks, 18 windows @180 chars) |
| Repeat run does not duplicate candidates | True (processed=0, skipped=18, cards=13 unique hashes) |
| Resume from partial cursor continues | True |
| Request records input_hash/chunk_ids/model/prompt/token/cost | True |
| Output status remains candidate-only | True |
| Offline deterministic path | True; API mode injectable caller only |

## Artifacts

- `tools/document_pipeline/cursor_generator.py`
- `tools/document_pipeline/fixtures/cursor_zhongyao_content_blocks.json`
- `tools/document_pipeline/fixtures/cursor_jichu_content_blocks.json`
- `tools/tests/test_cursor_generator.py`

## Run evidence

- Generator: `contentblock-cursor-generator`
- Prompt version: `p5t05-v1`
- zhongyao fixture: 22 blocks / 2189 chars / 18 windows / 13 cards
- zhongyao card types: herb_compatibility, herb_contrast, herb_function, herb_indication, herb_nature_flavor, herb_toxicity_caution, herb_usage
- jichu fixture: 13 blocks / 967 chars / 7 windows / 8 cards
- jichu card types: concept_definition, contrast, mechanism, relation
- Resume reload fix: previous `candidates.jsonl` always reloaded into memory so no-op second run returns same card set and does not rewrite empty file

## Notes

- Offline mode dispatches template extractors per window; no full-document prefix truncation.
- API mode requires injectable `model_caller` and walks every packed window.
- Cursor state persists completed chunk IDs, input hashes, candidate content hashes, and per-window requests.
- Legacy `cli_cards.py` still has `md[:max_chars]` path; full CLI cutover is optional follow-up, not required for T05 acceptance.

## Verification

- pytest: `tools/tests/test_cursor_generator.py` => 6 passed
- related suite: cursor + templates + schema + generate => 53 passed
- ruff: clean on cursor modules
- mypy: clean on `cursor_generator.py`
