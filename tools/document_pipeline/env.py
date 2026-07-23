"""Environment loading for offline tools. Never prints secrets."""

from __future__ import annotations

import os
from pathlib import Path

from tools.document_pipeline.paths import ROOT


def load_env(*, root: Path | None = None) -> None:
    base = root if root is not None else ROOT
    for name in (".env.local", ".env"):
        path = base / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def get_mineru_token() -> str:
    token = os.environ.get("MINERU_API_TOKEN") or os.environ.get("MINERU_TOKEN")
    if not token:
        raise SystemExit("MINERU_API_TOKEN is not set. Put it in .env.local or export it.")
    return token


# Backward-compatible alias used by legacy CLI modules.
get_token = get_mineru_token
