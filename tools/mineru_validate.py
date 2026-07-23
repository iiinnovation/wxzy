#!/usr/bin/env python3
"""MinerU local validation helper (compat entrypoint).

Implementation lives in tools.document_pipeline. CLI surface is unchanged:
  python tools/mineru_validate.py extract-pages|submit|poll|download|run-samples|...
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.document_pipeline.cli_mineru import main  # noqa: E402

if __name__ == "__main__":
    main()
