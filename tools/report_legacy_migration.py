#!/usr/bin/env python3
"""Read-only reconciliation report for the 20260723_0006 legacy migration.

The report never prints connection credentials.  By default it reads the checked-in local
database; set DATABASE_URL or pass --database-url for another database.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = f"sqlite+pysqlite:///{ROOT / 'server' / 'wxzy.db'}"
LEGACY_ATTEMPT_PREFIX = "legacy-review-log-"


def _utc_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return str(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _table_counts(engine: Engine, table_names: list[str]) -> dict[str, int]:
    existing = set(inspect(engine).get_table_names())
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in table_names:
            counts[table] = (
                int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
                if table in existing
                else 0
            )
    return counts


def build_report(engine: Engine) -> dict[str, Any]:
    tables = [
        "users",
        "learning_profiles",
        "user_sessions",
        "books",
        "cards",
        "review_states",
        "review_logs",
        "card_enrollments",
        "card_review_states",
        "study_sessions",
        "review_attempts",
        "card_issues",
    ]
    counts = _table_counts(engine, tables)
    errors: list[str] = []
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ).scalar_one_or_none()
        owner = (
            connection.execute(
                text(
                    "SELECT id, display_name, status, timezone FROM users "
                    "WHERE status = 'active' ORDER BY id LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
        if counts["cards"] and owner is None:
            errors.append("legacy cards exist but no active Owner was found")

        owner_id = int(owner["id"]) if owner is not None else None
        state_mismatches: list[int] = []
        if owner_id is not None:
            legacy_states = connection.execute(
                text(
                    "SELECT card_id, due_at, stability, difficulty, elapsed_days, "
                    "scheduled_days, reps, lapses, state, algorithm_version, last_rating, "
                    "last_reviewed_at FROM review_states ORDER BY card_id"
                )
            ).mappings()
            personal_states = {
                int(row["card_id"]): row
                for row in connection.execute(
                    text(
                        "SELECT card_id, due_at, stability, difficulty, elapsed_days, "
                        "scheduled_days, reps, lapses, state, algorithm_version, last_rating, "
                        "last_reviewed_at FROM card_review_states WHERE user_id = :user_id"
                    ),
                    {"user_id": owner_id},
                ).mappings()
            }
            for legacy in legacy_states:
                card_id = int(legacy["card_id"])
                personal = personal_states.get(card_id)
                if personal is None:
                    state_mismatches.append(card_id)
                    continue
                for field in (
                    "stability",
                    "difficulty",
                    "elapsed_days",
                    "scheduled_days",
                    "reps",
                    "lapses",
                    "state",
                    "algorithm_version",
                    "last_rating",
                ):
                    if personal[field] != legacy[field]:
                        state_mismatches.append(card_id)
                        break
                else:
                    if _utc_text(personal["due_at"]) != _utc_text(legacy["due_at"]):
                        state_mismatches.append(card_id)
                    elif _utc_text(personal["last_reviewed_at"]) != _utc_text(
                        legacy["last_reviewed_at"]
                    ):
                        state_mismatches.append(card_id)

            legacy_log_ids = {
                int(row["id"])
                for row in connection.execute(text("SELECT id FROM review_logs")).mappings()
            }
            attempt_keys = {
                str(row["client_attempt_id"])
                for row in connection.execute(
                    text("SELECT client_attempt_id FROM review_attempts WHERE user_id = :user_id"),
                    {"user_id": owner_id},
                ).mappings()
            }
            expected_attempt_keys = {
                f"{LEGACY_ATTEMPT_PREFIX}{log_id}" for log_id in legacy_log_ids
            }
            missing_attempt_keys = sorted(expected_attempt_keys - attempt_keys)
            extra_legacy_attempt_keys = sorted(
                key
                for key in attempt_keys
                if key.startswith(LEGACY_ATTEMPT_PREFIX) and key not in expected_attempt_keys
            )
        else:
            missing_attempt_keys = []
            extra_legacy_attempt_keys = []

        orphan_counts = {
            "card_enrollments": int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM card_enrollments e "
                        "LEFT JOIN users u ON u.id = e.user_id "
                        "LEFT JOIN cards c ON c.id = e.card_id "
                        "WHERE u.id IS NULL OR c.id IS NULL"
                    )
                ).scalar_one()
            ),
            "card_review_states": int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM card_review_states s "
                        "LEFT JOIN users u ON u.id = s.user_id "
                        "LEFT JOIN cards c ON c.id = s.card_id "
                        "WHERE u.id IS NULL OR c.id IS NULL"
                    )
                ).scalar_one()
            ),
            "review_attempts": int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM review_attempts a "
                        "LEFT JOIN users u ON u.id = a.user_id "
                        "LEFT JOIN cards c ON c.id = a.card_id "
                        "LEFT JOIN study_sessions s ON s.id = a.session_id "
                        "WHERE u.id IS NULL OR c.id IS NULL OR s.id IS NULL"
                    )
                ).scalar_one()
            ),
        }

    if revision != "20260723_0006":
        errors.append(f"database revision is {revision!r}, expected '20260723_0006'")
    if state_mismatches:
        errors.append(f"{len(state_mismatches)} legacy review states differ from personal states")
    if missing_attempt_keys:
        errors.append(f"missing {len(missing_attempt_keys)} legacy ReviewAttempt mappings")
    if extra_legacy_attempt_keys:
        errors.append(f"found {len(extra_legacy_attempt_keys)} unexpected legacy Attempt keys")
    errors.extend(f"{count} orphan {table} rows" for table, count in orphan_counts.items() if count)

    return {
        "ok": not errors,
        "revision": revision,
        "owner": dict(owner) if owner is not None else None,
        "counts": counts,
        "checks": {
            "legacy_state_mismatches": state_mismatches,
            "missing_attempt_keys": missing_attempt_keys,
            "unexpected_legacy_attempt_keys": extra_legacy_attempt_keys,
            "orphan_counts": orphan_counts,
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        payload = json.dumps(build_report(engine), ensure_ascii=False, indent=2, sort_keys=True)
    finally:
        engine.dispose()
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if json.loads(payload)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
