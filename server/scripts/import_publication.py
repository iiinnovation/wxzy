from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db import SessionLocal
from app.publishing.services import import_publication_package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a reviewed publication package")
    parser.add_argument("package_dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with SessionLocal() as db:
        result = import_publication_package(db, args.package_dir)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "imported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
