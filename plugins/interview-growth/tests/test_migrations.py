from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

from interview_growth.config import DataPaths
from interview_growth.persistence.database import connect_database
from interview_growth.persistence.migrations import (
    GOAL_MIGRATIONS,
    initialize_goal_database,
    initialize_registry_database,
)


def test_migrations_are_reentrant_and_databases_are_private(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "data")
    paths.ensure_layout()
    initialize_registry_database(paths.registry_database)
    initialize_registry_database(paths.registry_database)

    goal_id = "11111111-1111-4111-8111-111111111111"
    goal_database = paths.goal_database(goal_id)
    initialize_goal_database(goal_database, goal_id, "2026-07-19T10:00:00.000Z")
    initialize_goal_database(goal_database, goal_id, "2026-07-19T10:00:00.000Z")

    with sqlite3.connect(paths.registry_database) as connection:
        registry_versions = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()
    with sqlite3.connect(goal_database) as connection:
        goal_versions = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
        identity = connection.execute("SELECT id FROM goal_identity").fetchone()

    assert registry_versions == (2,)
    assert goal_versions == (5,)
    assert identity == (goal_id,)
    assert stat.S_IMODE(paths.registry_database.stat().st_mode) == 0o600
    assert stat.S_IMODE(goal_database.stat().st_mode) == 0o600


def test_existing_m0_goal_database_upgrades_through_m4(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "data")
    paths.ensure_layout()
    goal_id = "11111111-1111-4111-8111-111111111111"
    goal_database = paths.goal_database(goal_id)

    with connect_database(goal_database) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            );
            """
            + GOAL_MIGRATIONS[1]
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            ("2026-07-19T10:00:00.000Z",),
        )
        connection.execute(
            "INSERT INTO goal_identity(id, created_at) VALUES (?, ?)",
            (goal_id, "2026-07-19T10:00:00.000Z"),
        )
        connection.commit()

    initialize_goal_database(goal_database, goal_id, "2026-07-19T10:00:00.000Z")

    with sqlite3.connect(goal_database) as connection:
        version_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()
        question_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'questions'"
        ).fetchone()
    assert version_count == (5,)
    assert question_table == ("questions",)
    assert goal_database.with_name("goal.pre-migration-v2.sqlite").is_file()
    assert goal_database.with_name("goal.pre-migration-v5.sqlite").is_file()
