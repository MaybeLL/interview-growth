"""Identity-checked, idempotent access to one goal database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from interview_growth.domain.errors import IdempotencyConflictError

from .database import connect_database

WriteOperation = Callable[[sqlite3.Connection], dict[str, Any]]


def json_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("Stored JSON value is not an object.")
    return cast(dict[str, Any], value)


class GoalScopedStore:
    """Guard every read and write with the database's immutable goal identity."""

    def __init__(self, database_path: Path, expected_goal_id: str) -> None:
        self.database_path = database_path
        self.expected_goal_id = expected_goal_id

    def read(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        with connect_database(self.database_path) as connection:
            self._require_identity(connection)
            return operation(connection)

    def write_idempotent(
        self,
        *,
        operation_name: str,
        idempotency_key: str,
        request_hash: str,
        timestamp: str,
        operation: WriteOperation,
    ) -> dict[str, Any]:
        with connect_database(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._require_identity(connection)
                existing = connection.execute(
                    """
                    SELECT operation, request_hash, response_json
                    FROM idempotency_records WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["operation"] != operation_name
                        or existing["request_hash"] != request_hash
                    ):
                        raise IdempotencyConflictError(
                            "The idempotency key was already used with different input."
                        )
                    connection.rollback()
                    return json_object(existing["response_json"])

                response = operation(connection)
                connection.execute(
                    """
                    INSERT INTO idempotency_records(
                        idempotency_key, operation, request_hash, response_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        operation_name,
                        request_hash,
                        json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                        timestamp,
                    ),
                )
                connection.commit()
                return response
            except Exception:
                connection.rollback()
                raise

    def append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        payload: dict[str, Any],
        timestamp: str,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_log(event_type, payload_json, occurred_at) VALUES (?, ?, ?)",
            (
                event_type,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                timestamp,
            ),
        )

    def _require_identity(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT id FROM goal_identity").fetchone()
        if row is None or row["id"] != self.expected_goal_id:
            raise RuntimeError("Refusing to access a goal database with a mismatched identity.")
