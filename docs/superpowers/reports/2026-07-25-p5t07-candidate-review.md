# P5-T07 人工审核工作流

- Status: complete
- Generated: 2026-07-25T03:42:33.192263+00:00
- Tracked: review library/tests + this no-fulltext summary only.

## Acceptance

| Check | Result |
|---|---|
| Approve audit complete | True |
| Edit audit complete | True |
| Reject audit complete | True |
| Second review audit complete | True |
| Edit re-runs automated validation | True (bad edit blocked) |
| Critical cards cannot batch-approve | True |
| Static review bundle (JSON/MD/audit) | True |
| Output remains non-learning | True (`candidate_review_only`) |

## Artifacts

- `tools/document_pipeline/candidate_review.py`
- `tools/tests/test_candidate_review.py`
- reuses fixtures from `tools/document_pipeline/fixtures/validation_p5t06_cards.json`

## Workflow

- Decisions: approve / edit / reject / second_review
- Every action writes `AuditEvent` (before/after/reviewer/at/notes/error/validation)
- Edit and approve re-run schema gate + `candidate_validation.validate_card`
- Chapter batch approves only non-critical allowed risk levels; critical => `batch_skip`
- Bundle export: `review_bundle.json`, `cards.jsonl`, `audit.jsonl`, `REVIEW.md`

## Verification

- pytest: `tools/tests/test_candidate_review.py` => 4 passed
- related: review + validation + cursor + schema => 26 passed
- ruff/mypy: clean on `candidate_review.py`
- stage: `candidate_review` / `p5t07-v1`
