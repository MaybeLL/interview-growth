"""Registry repository for goal summaries and session bindings."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from interview_growth.domain.errors import GoalNotFoundError, IdempotencyConflictError
from interview_growth.domain.models import Goal, GoalLifecycle

from .database import connect_database


def _goal_from_row(row: sqlite3.Row) -> Goal:
    return Goal(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        lifecycle=GoalLifecycle(row["lifecycle"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class RegistryRepository:
    """Persist registry state without exposing raw SQL to application services."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def list_goals(self) -> tuple[Goal, ...]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, slug, name, lifecycle, created_at, updated_at
                FROM goals
                WHERE deleted_at IS NULL
                ORDER BY created_at, id
                """
            ).fetchall()
        return tuple(_goal_from_row(row) for row in rows)

    def get_goal(self, goal_id: str) -> Goal:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, slug, name, lifecycle, created_at, updated_at
                FROM goals WHERE id = ? AND deleted_at IS NULL
                """,
                (goal_id,),
            ).fetchone()
        if row is None:
            raise GoalNotFoundError(f"Unknown goal ID: {goal_id}")
        return _goal_from_row(row)

    def get_goal_database_path(self, goal_id: str) -> Path:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                "SELECT database_path FROM goals WHERE id = ? AND deleted_at IS NULL",
                (goal_id,),
            ).fetchone()
        if row is None:
            raise GoalNotFoundError(f"Unknown goal ID: {goal_id}")
        return Path(row["database_path"])

    def find_idempotent_goal(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> Goal | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT request_hash, response_json
                FROM idempotency_records
                WHERE scope = 'registry' AND idempotency_key = ? AND operation = 'goal_create'
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError(
                "The idempotency key was already used with different goal input."
            )
        response = json.loads(row["response_json"])
        return self.get_goal(response["goal_id"])

    def insert_goal(
        self,
        *,
        goal: Goal,
        database_path: Path,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        response_json = json.dumps({"goal_id": goal.id}, separators=(",", ":"))
        with connect_database(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO goals(
                        id, slug, name, lifecycle, database_path, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        goal.id,
                        goal.slug,
                        goal.name,
                        goal.lifecycle.value,
                        str(database_path),
                        goal.created_at,
                        goal.updated_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO idempotency_records(
                        scope, idempotency_key, operation, request_hash, response_json, created_at
                    ) VALUES ('registry', ?, 'goal_create', ?, ?, ?)
                    """,
                    (idempotency_key, request_hash, response_json, goal.created_at),
                )
                connection.commit()
            except sqlite3.Error:
                connection.rollback()
                raise

    def bind_session(self, *, session_id: str, goal_id: str, timestamp: str) -> Goal:
        goal = self.get_goal(goal_id)
        with connect_database(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO session_bindings(session_id, goal_id, bound_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    goal_id = excluded.goal_id,
                    bound_at = excluded.bound_at,
                    updated_at = excluded.updated_at
                """,
                (session_id, goal_id, timestamp, timestamp),
            )
            connection.commit()
        return goal

    def get_bound_goal(self, session_id: str) -> Goal | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT g.id, g.slug, g.name, g.lifecycle, g.created_at, g.updated_at
                FROM session_bindings AS b
                JOIN goals AS g ON g.id = b.goal_id
                WHERE b.session_id = ? AND g.deleted_at IS NULL
                """,
                (session_id,),
            ).fetchone()
        return None if row is None else _goal_from_row(row)

    def update_lifecycle(
        self,
        *,
        goal_id: str,
        expected: GoalLifecycle,
        requested: GoalLifecycle,
        timestamp: str,
    ) -> Goal:
        with connect_database(self._database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE goals
                SET lifecycle = ?, updated_at = ?
                WHERE id = ? AND lifecycle = ?
                """,
                (requested.value, timestamp, goal_id, expected.value),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError("Goal lifecycle changed concurrently; reload and retry.")
            connection.commit()
        return self.get_goal(goal_id)

    def find_operation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT operation, request_hash, response_json
                FROM idempotency_records
                WHERE scope = 'portability' AND idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_hash"] != request_hash:
            raise IdempotencyConflictError(
                "The idempotency key was already used with different portability input."
            )
        value = json.loads(row["response_json"])
        if not isinstance(value, dict):
            raise RuntimeError("Stored portability response is invalid.")
        return cast(dict[str, Any], value)

    def record_operation(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        response: dict[str, Any],
        timestamp: str,
    ) -> None:
        with connect_database(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    scope, idempotency_key, operation, request_hash,
                    response_json, created_at
                ) VALUES ('portability', ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    operation,
                    request_hash,
                    json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                ),
            )
            connection.commit()

    def record_backup(
        self,
        *,
        backup_id: str,
        goal_id: str,
        database_path: Path,
        sha256: str,
        reason: str,
        timestamp: str,
    ) -> dict[str, Any]:
        with connect_database(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO goal_backups(
                    id, goal_id, database_path, sha256, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (backup_id, goal_id, str(database_path), sha256, reason, timestamp),
            )
            connection.commit()
        return self.get_backup(backup_id)

    def get_backup(self, backup_id: str) -> dict[str, Any]:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                "SELECT * FROM goal_backups WHERE id = ?", (backup_id,)
            ).fetchone()
        if row is None:
            raise GoalNotFoundError(f"Unknown backup ID: {backup_id}")
        return dict(row)

    def list_backups(self, goal_id: str) -> list[dict[str, Any]]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM goal_backups
                WHERE goal_id = ? ORDER BY created_at DESC, id DESC
                """,
                (goal_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_deleted(
        self,
        *,
        goal_id: str,
        trash_path: Path,
        timestamp: str,
    ) -> None:
        with connect_database(self._database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    """
                    UPDATE goals
                    SET deleted_at = ?, trash_path = ?, updated_at = ?
                    WHERE id = ? AND deleted_at IS NULL
                    """,
                    (timestamp, str(trash_path), timestamp, goal_id),
                )
                if cursor.rowcount != 1:
                    raise GoalNotFoundError(f"Unknown goal ID: {goal_id}")
                connection.execute(
                    "DELETE FROM session_bindings WHERE goal_id = ?", (goal_id,)
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
