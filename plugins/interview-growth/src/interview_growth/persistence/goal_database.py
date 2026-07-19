"""Operations that are deliberately scoped to one goal database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import connect_database


class GoalDatabaseRepository:
    """Access a single goal database after its identity has been validated."""

    def __init__(self, database_path: Path, expected_goal_id: str) -> None:
        self._database_path = database_path
        self._expected_goal_id = expected_goal_id

    def verify_identity(self) -> bool:
        if not self._database_path.is_file():
            return False
        with connect_database(self._database_path) as connection:
            row = connection.execute("SELECT id FROM goal_identity").fetchone()
        return row is not None and row["id"] == self._expected_goal_id

    def append_audit_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: str,
    ) -> None:
        if not self.verify_identity():
            raise RuntimeError("Refusing to write a goal database with a mismatched identity.")
        with connect_database(self._database_path) as connection:
            connection.execute(
                "INSERT INTO audit_log(event_type, payload_json, occurred_at) VALUES (?, ?, ?)",
                (
                    event_type,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    occurred_at,
                ),
            )
            connection.commit()
