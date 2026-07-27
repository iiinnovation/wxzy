from __future__ import annotations

import argparse

from app import models as _models  # noqa: F401
from app.db import SessionLocal
from app.identity.auth import MobileActivationUnavailableError, issue_mobile_activation_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Issue a one-time activation code for Wenxi Android"
    )
    parser.add_argument("--ttl-minutes", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.ttl_minutes <= 24 * 60:
        parser.error("--ttl-minutes must be between 1 and 1440")

    with SessionLocal() as db:
        try:
            code = issue_mobile_activation_code(db, ttl_seconds=args.ttl_minutes * 60)
        except MobileActivationUnavailableError:
            parser.error("no active Owner exists; complete Owner binding before issuing a code")
    print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
