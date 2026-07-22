from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = ROOT / "server" / "alembic.ini"
BASELINE_REVISION = "20260722_0001"
USER_TABLES = {"books", "cards", "review_states", "review_logs"}


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


def sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in rows}


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
    assert table_names(database) == USER_TABLES | {"alembic_version"}

    run_alembic(url, "downgrade", "-1")
    assert table_names(database) == {"alembic_version"}
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version is None

    run_alembic(url, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (BASELINE_REVISION,)
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

    run_alembic(url, "stamp", "head")
    run_alembic(url, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in USER_TABLES
        }
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert counts == {"books": 2, "cards": 15, "review_states": 15, "review_logs": 4}
    assert version == (BASELINE_REVISION,)
    run_alembic(url, "check")


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
    assert postgres_state(url) == (USER_TABLES | {"alembic_version"}, BASELINE_REVISION)

    run_alembic(url, "downgrade", "-1")
    assert postgres_state(url) == ({"alembic_version"}, None)

    run_alembic(url, "upgrade", "head")
    assert postgres_state(url) == (USER_TABLES | {"alembic_version"}, BASELINE_REVISION)
    run_alembic(url, "check")
