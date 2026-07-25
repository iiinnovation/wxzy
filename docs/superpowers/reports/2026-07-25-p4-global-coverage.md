# P4 Global Coverage Report (P4-T09)

- Generated: `2026-07-25T01:45:49Z`
- Corpus: **7** books / **704** design pages / **704** observed
- Terminal: pass **136** / needs_review **568** / fail **0**
- Acceptance met: **True**
- P4 exit gate met: **True**

## GitHub policy

- Source PDF / split PDF / raw OCR / cleaned & structured full text: **local only** (`data/`, `docs/*.pdf` gitignored).
- Tracked: this no-fulltext global summary + per-book coverage reports + schema/rules/fixtures only.

## Acceptance

- Criterion: total=704, every page terminal (pass or explicit needs_review); all non-pass have owner/reason/disposition; no silent fail; no page missing
- Met: **True**
- Pages: total=704, terminal=704, missing=0
- pass=136, needs_review=568, fail=0
- Books complete: 7/7; all book acceptance met: **True**
- All page ranges contiguous: **True**
- All page maps complete: **True**
- Local raw/cleaned/structured recoverable: **True**
- Non-pass splits with owner/reason/disposition: **25** / pages **568**

## P4 exit gate

- 704/704 pages with status + source map: **704/704**
- 7 books with chapter tree + quality report: **7/7**
- Full raw/cleaned/structured recoverable: **True**

## Books

| book | task | pages | pass | needs_review | fail | page_map | contiguous | chapters | blocks | tracked |
|------|------|------:|-----:|-------------:|-----:|----------|------------|---------:|-------:|---------|
| jichu | P4-T02 | 102 | 0 | 102 | 0 | 5/5 | True | 76 | 309 | `2026-07-24-jichu-p4t02.json` |
| zhenduan | P4-T03 | 92 | 46 | 46 | 0 | 4/4 | True | 85 | 451 | `2026-07-24-zhenduan-p4t03.json` |
| zhongyao | P4-T04 | 88 | 66 | 22 | 0 | 4/4 | True | 115 | 288 | `2026-07-24-zhongyao-p4t04.json` |
| fangji | P4-T05 | 140 | 0 | 140 | 0 | 6/6 | True | 110 | 341 | `2026-07-24-fangji-p4t05.json` |
| neike | P4-T06 | 149 | 24 | 125 | 0 | 6/6 | True | 100 | 539 | `2026-07-24-neike-p4t06.json` |
| zhenjiu | P4-T07 | 94 | 0 | 94 | 0 | 4/4 | True | 43 | 235 | `2026-07-24-zhenjiu-p4t07.json` |
| renwen | P4-T08 | 39 | 0 | 39 | 0 | 2/2 | True | 48 | 129 | `2026-07-24-renwen-p4t08.json` |

## Aggregates

- Chapters (sum): 577 (low-confidence: 107)
- Content blocks: 2292
- Table blocks: 793
- Full-run splits: 31
- Issue family split hits: {'suspicious_ocr_source': 5, 'empty_pages': 24}
- Budget after final full run (renwen): {'file_budget': 5000, 'page_budget': 1000, 'files_used': 38, 'pages_used': 774, 'files_remaining': 4962, 'pages_remaining': 226}

## Needs-review disposition policy

- `pass`: residual publication eligibility after P5 gates.
- `needs_review`: explicit terminal; publication blocked; owner=`pipeline-ops`; residual clean + human review required.
- `fail`: must carry owner/reason/action; **none** in P4 full runs.
- Do not collapse needs_review into “overall complete”.

## Non-pass splits (explicit)

| book | pages | status | reason | owner | disposition | publication |
|------|-------|--------|--------|-------|-------------|-------------|
| jichu | None-None (21) | **needs_review** | empty_pages,suspicious_ocr_source | pipeline-ops | human_review_image_or_watermark_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| jichu | None-None (21) | **needs_review** | empty_pages,suspicious_ocr_source | pipeline-ops | human_review_image_or_watermark_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| jichu | None-None (20) | **needs_review** | empty_pages,suspicious_ocr_source | pipeline-ops | human_review_image_or_watermark_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| jichu | None-None (20) | **needs_review** | suspicious_ocr_source | pipeline-ops | human_review_ocr_source; residual_clean_pass; block_publication_until_reviewed | blocked |
| jichu | None-None (20) | **needs_review** | empty_pages,suspicious_ocr_source | pipeline-ops | human_review_image_or_watermark_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenduan | 24-46 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenduan | 47-69 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhongyao | 23-44 (22) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 1-24 (24) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 25-48 (24) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 49-71 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 72-94 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 95-117 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| fangji | 118-140 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| neike | 1-25 (25) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| neike | 26-50 (25) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| neike | 51-75 (25) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| neike | 76-100 (25) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| neike | 101-125 (25) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenjiu | 1-24 (24) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenjiu | 25-48 (24) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenjiu | 49-71 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| zhenjiu | 72-94 (23) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| renwen | 1-20 (20) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |
| renwen | 21-39 (19) | **needs_review** | empty_pages | pipeline-ops | human_review_near_empty_pages; residual_clean_pass; block_publication_until_reviewed | blocked |

## Disposition summary

704/704 pages terminal: pass=136, needs_review=568, fail=0. 25 non-pass splits (568 pages) each have owner=pipeline-ops, reason codes, and blocked publication disposition. No silent fails. All 7 books have complete page maps, contiguous page ranges, chapter trees, quality reports, and recoverable local raw/cleaned/structured artifacts.

## Local artifacts (not in git)

- Per-book jobs under `data/document-pipeline/jobs/*_p4t0*_v1/` (raw/cleaned/structured/quality).
- Per-book splits under `data/document-pipeline/splits/<document_version>/`.
- Local copy of this report: `data/document-pipeline/coverage/p4-global-coverage.v1.{json,md}`.
