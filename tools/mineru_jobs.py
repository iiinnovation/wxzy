#!/usr/bin/env python3
"""MinerU job lifecycle CLI (compat entrypoint).

python tools/mineru_jobs.py create|submit|poll|download|show|create-from-split ...
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.document_pipeline.cli_jobs import main  # noqa: E402

if __name__ == "__main__":
    main()
