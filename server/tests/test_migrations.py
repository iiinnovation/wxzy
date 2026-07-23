from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = ROOT / "server" / "alembic.ini"
BASELINE_REVISION = "20260722_0001"
IDENTITY_REVISION = "20260722_0002"
CATALOG_REVISION = "20260722_0003"
ENROLLMENT_REVISION = "20260722_0004"
ATTEMPT_REVISION = "20260722_0005"
DATA_REVISION = "20260723_0006"
BASELINE_TABLES = {"books", "cards", "review_states", "review_logs"}
IDENTITY_TABLES = {"users", "user_sessions", "learning_profiles"}
CATALOG_TABLES = {
    "documents",
    "document_versions",
    "chapters",
    "document_chunks",
    "card_sources",
}
ENROLLMENT_TABLES = {"card_enrollments", "card_review_states"}
ATTEMPT_TABLES = {"study_sessions", "review_attempts", "card_issues"}
PRE_CATALOG_TABLES = BASELINE_TABLES | IDENTITY_TABLES
PRE_ENROLLMENT_TABLES = PRE_CATALOG_TABLES | CATALOG_TABLES
PRE_ATTEMPT_TABLES = PRE_ENROLLMENT_TABLES | ENROLLMENT_TABLES
HEAD_TABLES = PRE_ATTEMPT_TABLES | ATTEMPT_TABLES


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def run_alembic_allow_failure(
    database_url: str, *arguments: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in rows}


def assert_sqlite_single_active_owner_constraint(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO users (status, timezone) VALUES ('active', 'UTC')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO users (status, timezone) VALUES ('active', 'UTC')")
        connection.execute("INSERT INTO users (status, timezone) VALUES ('disabled', 'UTC')")
        connection.execute("INSERT INTO users (status, timezone) VALUES ('disabled', 'UTC')")
        counts = connection.execute(
            "SELECT status, COUNT(*) FROM users GROUP BY status ORDER BY status"
        ).fetchall()
    assert counts == [("active", 1), ("disabled", 2)]


def assert_postgres_single_active_owner_constraint(url: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (status, timezone) VALUES ('active', 'UTC')")
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO users (status, timezone) VALUES ('active', 'UTC')")
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (status, timezone) "
                    "VALUES ('disabled', 'UTC'), ('disabled', 'UTC')"
                )
            )
            counts = connection.execute(
                text("SELECT status, COUNT(*) FROM users GROUP BY status ORDER BY status")
            ).all()
        assert counts == [("active", 1), ("disabled", 2)]
    finally:
        engine.dispose()


def test_app_startup_does_not_create_database_schema(tmp_path: Path) -> None:
    database = tmp_path / "startup.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = sqlite_url(database)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi.testclient import TestClient; "
                "from app.main import app; "
                "client = TestClient(app); "
                "assert client.get('/health').status_code == 200"
            ),
        ],
        cwd=ROOT / "server",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not database.exists()


def test_empty_sqlite_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    url = sqlite_url(database)

    run_alembic(url, "upgrade", "head")
    assert table_names(database) == HEAD_TABLES | {"alembic_version"}
    assert_sqlite_single_active_owner_constraint(database)

    run_alembic(url, "downgrade", "-1")
    assert table_names(database) == HEAD_TABLES | {"alembic_version"}
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (ATTEMPT_REVISION,)

    run_alembic(url, "downgrade", "-1")
    assert table_names(database) == PRE_ATTEMPT_TABLES | {"alembic_version"}
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (ENROLLMENT_REVISION,)

    run_alembic(url, "downgrade", "-1")
    assert table_names(database) == PRE_ENROLLMENT_TABLES | {"alembic_version"}
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (CATALOG_REVISION,)

    run_alembic(url, "downgrade", "-1")
    assert table_names(database) == PRE_CATALOG_TABLES | {"alembic_version"}
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (IDENTITY_REVISION,)

    run_alembic(url, "downgrade", "base")
    assert table_names(database) == {"alembic_version"}

    run_alembic(url, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (DATA_REVISION,)
    run_alembic(url, "check")


def create_legacy_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE books (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                subject VARCHAR(64),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE UNIQUE INDEX ix_books_name ON books (name);
            CREATE TABLE cards (
                id INTEGER NOT NULL PRIMARY KEY,
                external_id VARCHAR(128) NOT NULL,
                book_id INTEGER NOT NULL,
                chapter VARCHAR(128),
                section VARCHAR(128),
                card_type VARCHAR(64) NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                answer_points_json TEXT,
                source_excerpt TEXT NOT NULL,
                source_pages_json TEXT,
                tags_json TEXT,
                status VARCHAR(32) NOT NULL,
                confidence FLOAT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CONSTRAINT uq_cards_external_id UNIQUE (external_id),
                FOREIGN KEY(book_id) REFERENCES books (id)
            );
            CREATE INDEX ix_cards_external_id ON cards (external_id);
            CREATE INDEX ix_cards_book_id ON cards (book_id);
            CREATE INDEX ix_cards_status ON cards (status);
            CREATE TABLE review_states (
                id INTEGER NOT NULL PRIMARY KEY,
                card_id INTEGER NOT NULL,
                due_at DATETIME NOT NULL,
                stability FLOAT NOT NULL,
                difficulty FLOAT NOT NULL,
                elapsed_days FLOAT NOT NULL,
                scheduled_days FLOAT NOT NULL,
                reps INTEGER NOT NULL,
                lapses INTEGER NOT NULL,
                state VARCHAR(32) NOT NULL,
                algorithm_version VARCHAR(32) NOT NULL,
                last_rating INTEGER,
                last_reviewed_at DATETIME,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(card_id) REFERENCES cards (id)
            );
            CREATE UNIQUE INDEX ix_review_states_card_id ON review_states (card_id);
            CREATE INDEX ix_review_states_due_at ON review_states (due_at);
            CREATE TABLE review_logs (
                id INTEGER NOT NULL PRIMARY KEY,
                card_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                due_before DATETIME,
                due_after DATETIME,
                stability_after FLOAT,
                difficulty_after FLOAT,
                algorithm_version VARCHAR(32) NOT NULL,
                state_before VARCHAR(32),
                state_after VARCHAR(32),
                FOREIGN KEY(card_id) REFERENCES cards (id)
            );
            CREATE INDEX ix_review_logs_card_id ON review_logs (card_id);
            """
        )
        connection.executemany(
            "INSERT INTO books (id, name, subject) VALUES (?, ?, ?)",
            [(1, "方剂学", "方剂"), (2, "中医内科学", "内科")],
        )
        connection.executemany(
            """
            INSERT INTO cards (
                id, external_id, book_id, card_type, question, answer, source_excerpt, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index,
                    f"legacy-{index}",
                    1 if index <= 8 else 2,
                    "other",
                    f"问题{index}",
                    f"答案{index}",
                    "原文",
                    "approved",
                )
                for index in range(1, 16)
            ],
        )
        connection.executemany(
            """
            INSERT INTO review_states (
                id, card_id, due_at, stability, difficulty, elapsed_days, scheduled_days,
                reps, lapses, state, algorithm_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index,
                    index,
                    "2026-07-22 08:00:00",
                    1.0,
                    5.0,
                    0.0,
                    0.0,
                    0,
                    0,
                    "new",
                    "fsrs-v1",
                )
                for index in range(1, 16)
            ],
        )
        connection.executemany(
            "INSERT INTO review_logs (id, card_id, rating, algorithm_version) VALUES (?, ?, ?, ?)",
            [(index, index, 3, "fsrs-v1") for index in range(1, 5)],
        )
        connection.commit()


def test_legacy_sqlite_can_stamp_and_upgrade_without_data_loss(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    create_legacy_schema(database)
    url = sqlite_url(database)

    run_alembic(url, "stamp", BASELINE_REVISION)
    run_alembic(url, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in BASELINE_TABLES
        }
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        card_defaults = connection.execute(
            "SELECT MIN(content_revision), MAX(content_revision), "
            "MIN(answer_points), MAX(answer_points), MIN(tags), MAX(tags) FROM cards"
        ).fetchone()
        migrated_counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "users",
                "learning_profiles",
                "card_enrollments",
                "card_review_states",
                "study_sessions",
                "review_attempts",
            )
        }
        enrollment_statuses = connection.execute(
            "SELECT status, source, COUNT(*) FROM card_enrollments GROUP BY status, source"
        ).fetchall()
        legacy_state_values = connection.execute(
            "SELECT card_id, due_at, reps, lapses FROM review_states ORDER BY card_id"
        ).fetchall()
        personal_state_values = connection.execute(
            "SELECT card_id, due_at, reps, lapses FROM card_review_states ORDER BY card_id"
        ).fetchall()
        attempt_keys = connection.execute(
            "SELECT client_attempt_id FROM review_attempts ORDER BY id"
        ).fetchall()
    assert counts == {"books": 2, "cards": 15, "review_states": 15, "review_logs": 4}
    assert version == (DATA_REVISION,)
    assert card_defaults == (1, 1, "[]", "[]", "[]", "[]")
    assert migrated_counts == {
        "users": 1,
        "learning_profiles": 1,
        "card_enrollments": 15,
        "card_review_states": 15,
        "study_sessions": 1,
        "review_attempts": 4,
    }
    assert enrollment_statuses == [("active", "manual", 15)]
    assert [
        (card_id, due_at.split(".", 1)[0], reps, lapses)
        for card_id, due_at, reps, lapses in personal_state_values
    ] == [
        (card_id, due_at.split(".", 1)[0], reps, lapses)
        for card_id, due_at, reps, lapses in legacy_state_values
    ]
    assert attempt_keys == [(f"legacy-review-log-{index}",) for index in range(1, 5)]
    assert table_names(database) == HEAD_TABLES | {"alembic_version"}
    run_alembic(url, "check")


def test_legacy_data_migration_refuses_destructive_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "legacy-downgrade.db"
    create_legacy_schema(database)
    url = sqlite_url(database)

    run_alembic(url, "stamp", BASELINE_REVISION)
    run_alembic(url, "upgrade", "head")
    result = run_alembic_allow_failure(url, "downgrade", "-1")

    assert result.returncode != 0
    assert "restore the pre-migration backup" in result.stdout + result.stderr


def postgres_state(url: str) -> tuple[set[str], str | None]:
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        if "alembic_version" not in tables:
            return tables, None
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return tables, version
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_empty_postgres_upgrade_when_configured() -> None:
    url = os.environ.get("WXZY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set WXZY_TEST_POSTGRES_URL to run the PostgreSQL migration check")

    database_name = make_url(url).database or ""
    assert "test" in database_name or database_name.startswith("wxzy_p0_")

    run_alembic(url, "downgrade", "base")
    assert postgres_state(url) == ({"alembic_version"}, None)

    run_alembic(url, "upgrade", "head")
    assert postgres_state(url) == (HEAD_TABLES | {"alembic_version"}, DATA_REVISION)
    assert_postgres_single_active_owner_constraint(url)

    run_alembic(url, "downgrade", "-1")
    assert postgres_state(url) == (HEAD_TABLES | {"alembic_version"}, ATTEMPT_REVISION)

    run_alembic(url, "downgrade", "-1")
    assert postgres_state(url) == (
        PRE_ATTEMPT_TABLES | {"alembic_version"},
        ENROLLMENT_REVISION,
    )

    run_alembic(url, "downgrade", "-1")
    assert postgres_state(url) == (
        PRE_ENROLLMENT_TABLES | {"alembic_version"},
        CATALOG_REVISION,
    )

    run_alembic(url, "downgrade", "-1")
    assert postgres_state(url) == (PRE_CATALOG_TABLES | {"alembic_version"}, IDENTITY_REVISION)

    run_alembic(url, "downgrade", "base")
    assert postgres_state(url) == ({"alembic_version"}, None)

    run_alembic(url, "upgrade", "head")
    assert postgres_state(url) == (HEAD_TABLES | {"alembic_version"}, DATA_REVISION)
    run_alembic(url, "check")
