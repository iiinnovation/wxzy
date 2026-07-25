# P5-T08 Publication Exporter

- Status: complete
- Generated: 2026-07-25T03:45:38.663305+00:00
- Tracked: exporter/tests + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| Package layout complete | True (manifest/documents/chapters/chunks/cards/sources/checksums/quality-summary) |
| Hash recomputable | True (`verify_package_checksums`) |
| Unreviewed cards cannot export | True |
| Missing citations cannot export | True |
| Critical requires reviewer/reviewed_at | True |
| No local abs paths / secrets | True |

## Artifacts

- `tools/document_pipeline/publish.py`
- `tools/tests/test_publication_export.py`

## Package contract

```text
publication/
  manifest.json
  documents.json
  chapters.json
  chunks.jsonl
  cards.jsonl
  card_sources.jsonl
  checksums.json
  quality-summary.json
```

- `checksums.json.files[*]` = sha256 of file bytes
- `package_hash` = sha256(canonical_json(files map))
- `manifest_hash` recorded after package content hash

## Verification

- pytest: `tools/tests/test_publication_export.py` => 4 passed
- related: export + review + validation + cursor + schema => 30 passed
- ruff/mypy: clean on `publish.py`
- stage: `publication_export` / `p5t08-v1`
