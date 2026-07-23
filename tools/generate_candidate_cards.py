#!/usr/bin/env python3
"""Generate candidate study cards (compat entrypoint).

Implementation lives in tools.document_pipeline.generation / cli_cards.
CLI surface is unchanged:
  python tools/generate_candidate_cards.py offline|api ...
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Re-export pure helpers used by unit tests and external imports.
from tools.document_pipeline.cli_cards import main  # noqa: E402
from tools.document_pipeline.generation import (  # noqa: E402, F401
    PROMPT_VERSION,
    TableParser,
    call_qwen_api,
    card,
    extract_formula_cards,
    extract_neike_pulmonary_tb_cards,
    extract_versioned_zhongfeng_cards,
    merge_formula_blocks,
    now_iso,
    parse_html_tables,
    stable_id,
    table_to_kv_blocks,
    write_review_md,
)

if __name__ == "__main__":
    main()
