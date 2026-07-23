#!/usr/bin/env python3
"""Chapter-aware PDF split CLI (compat entrypoint).

python tools/split_pdfs.py
python tools/split_pdfs.py --plan-only --document-key renwen
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.document_pipeline.cli_split import main  # noqa: E402

if __name__ == "__main__":
    main()
