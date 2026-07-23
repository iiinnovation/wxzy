#!/usr/bin/env python3
"""Document inventory CLI (compat entrypoint).

python tools/inventory_scan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.document_pipeline.cli_inventory import main  # noqa: E402

if __name__ == "__main__":
    main()
