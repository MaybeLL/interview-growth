"""Persistence for immutable question versions and their mappings."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from interview_growth.domain.errors import DomainValidationError, VersionConflictError
from interview_growth.domain.models import Question, QuestionStatus, QuestionVersion

from .scoped import GoalScopedStore, json_object


def _version(connection: sqlite3.Connection, row: sqlite3.Row) -> QuestionVersion:
    topics = connection.execute(
        """
        SELECT topic_id FROM question_version_topics
        WHERE question_id = ? AND question_version = ? ORDER BY topic_id
        """,
        (row["question_id"], row["version"]),
    ).fetchall()
    capabilities = connection.execute(
        """
        SELECT capability_id FROM question_version_capabilities
        WHERE question_id = ? AND question_version = ? ORDER BY capability_id
        """,
        (row["question_id"], row["version"]),
    ).fetchall()
    return QuestionVersion(
        question_id=row["question_id"],
        version=row["version"],
        prompt=row["prompt"],
        intent=row["intent"],
        rubric=None if row["rubric_json"] is None else json_object(row["rubric_json"]),
        topic_ids=tuple(item["topic_id"] for item in topics),
        capability_ids=tuple(item["capability_id"] for item in capabilities),
        created_at=row["created_at"],
    )


def _question(connection: sqlite3.Connection, row: sqlite3.Row) -> Question:
    version_row = connection.execute(
        """
        SELECT question_id, version, prompt, intent, rubric_json, created_at
        FROM question_versions WHERE question_id = ? AND version = ?
        """,
        (row["id"], row["current_version"]),
    ).fetchone()
    if version_row is None:
        raise RuntimeError("Question current version is missing.")
    return Question(
        id=row["id"],
        status=QuestionStatus(row["status"]),
        source=row["source"],
        current_version=row["current_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retired_at=row["retired_at"],
        version=_version(connection, version_row),
    )


class QuestionRepository:
    def __init__(self, database_path: Path, goal_id: str) -> None:
        self._store = GoalScopedStore(database_path, goal_id)

    def capture(
        self,
        *,
        question: Question,
        idempotency_key: str,
        request_hash: str,
    ) -> Question:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            self._require_mappings(
                connection,
                topic_ids=question.version.topic_ids,
                capability_ids=question.version.capability_ids,
            )
            connection.execute(
                """
                INSERT INTO questions(
                    id, status, source, current_version, created_at, updated_at
                ) VALUES (?, 'pending', ?, 1, ?, ?)
                """,
                (question.id, question.source, question.created_at, question.updated_at),
            )
            self._insert_version(connection, question.version)
            self._store.append_audit(
                connection,
                event_type="question_captured",
                payload={"question_id": question.id, "version": 1},
                timestamp=question.created_at,
            )
            return {"question_id": question.id}

        response = self._store.write_idempotent(
            operation_name="question_capture",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=question.created_at,
            operation=write,
        )
        return self.get(str(response["question_id"]))

    def prepare_version(
        self,
        *,
        version: QuestionVersion,
        expected_current_version: int,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Question:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            question = connection.execute(
                "SELECT status, current_version FROM questions WHERE id = ?",
                (version.question_id,),
            ).fetchone()
            if question is None:
                raise DomainValidationError(f"Unknown question ID: {version.question_id}")
            if question["status"] == QuestionStatus.RETIRED.value:
                raise DomainValidationError("A retired question cannot receive a new version.")
            if question["current_version"] != expected_current_version:
                raise VersionConflictError("Question version changed; reload and retry.")
            if version.version != expected_current_version + 1:
                raise RuntimeError("Prepared question version number is not sequential.")
            self._require_mappings(
                connection,
                topic_ids=version.topic_ids,
                capability_ids=version.capability_ids,
            )
            self._insert_version(connection, version)
            connection.execute(
                """
                UPDATE questions
                SET status = 'assessable', current_version = ?, updated_at = ?
                WHERE id = ? AND current_version = ?
                """,
                (
                    version.version,
                    timestamp,
                    version.question_id,
                    expected_current_version,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="question_version_prepared",
                payload={"question_id": version.question_id, "version": version.version},
                timestamp=timestamp,
            )
            return {"question_id": version.question_id}

        response = self._store.write_idempotent(
            operation_name="question_prepare_version",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["question_id"]))

    def retire(
        self,
        *,
        question_id: str,
        expected_current_version: int,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Question:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT status, current_version FROM questions WHERE id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown question ID: {question_id}")
            if row["current_version"] != expected_current_version:
                raise VersionConflictError("Question version changed; reload and retry.")
            if row["status"] != QuestionStatus.RETIRED.value:
                connection.execute(
                    """
                    UPDATE questions SET status = 'retired', retired_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, question_id),
                )
                self._store.append_audit(
                    connection,
                    event_type="question_retired",
                    payload={"question_id": question_id},
                    timestamp=timestamp,
                )
            return {"question_id": question_id}

        response = self._store.write_idempotent(
            operation_name="question_retire",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["question_id"]))

    def get(self, question_id: str) -> Question:
        def read(connection: sqlite3.Connection) -> Question:
            row = connection.execute(
                "SELECT * FROM questions WHERE id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown question ID: {question_id}")
            return _question(connection, row)

        return self._store.read(read)

    def history(self, question_id: str) -> tuple[QuestionVersion, ...]:
        def read(connection: sqlite3.Connection) -> tuple[QuestionVersion, ...]:
            exists = connection.execute(
                "SELECT 1 FROM questions WHERE id = ?", (question_id,)
            ).fetchone()
            if exists is None:
                raise DomainValidationError(f"Unknown question ID: {question_id}")
            rows = connection.execute(
                """
                SELECT question_id, version, prompt, intent, rubric_json, created_at
                FROM question_versions WHERE question_id = ? ORDER BY version
                """,
                (question_id,),
            ).fetchall()
            return tuple(_version(connection, row) for row in rows)

        return self._store.read(read)

    def get_version(self, question_id: str, version: int) -> QuestionVersion:
        def read(connection: sqlite3.Connection) -> QuestionVersion:
            row = connection.execute(
                """
                SELECT question_id, version, prompt, intent, rubric_json, created_at
                FROM question_versions WHERE question_id = ? AND version = ?
                """,
                (question_id, version),
            ).fetchone()
            if row is None:
                raise DomainValidationError(
                    f"Unknown question version: {question_id} v{version}"
                )
            return _version(connection, row)

        return self._store.read(read)

    def search(
        self,
        *,
        query: str,
        topic_id: str | None,
        status: QuestionStatus | None,
        limit: int,
    ) -> tuple[Question, ...]:
        def read(connection: sqlite3.Connection) -> tuple[Question, ...]:
            parameters: list[object] = [f"%{query}%"]
            joins = ""
            where = ["version.prompt LIKE ? COLLATE NOCASE"]
            if topic_id is not None:
                joins = """
                    JOIN question_version_topics AS mapping
                      ON mapping.question_id = question.id
                     AND mapping.question_version = question.current_version
                """
                where.append("mapping.topic_id = ?")
                parameters.append(topic_id)
            if status is not None:
                where.append("question.status = ?")
                parameters.append(status.value)
            parameters.append(limit)
            rows = connection.execute(
                f"""
                SELECT DISTINCT question.*
                FROM questions AS question
                JOIN question_versions AS version
                  ON version.question_id = question.id
                 AND version.version = question.current_version
                {joins}
                WHERE {' AND '.join(where)}
                ORDER BY question.updated_at DESC, question.id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            return tuple(_question(connection, row) for row in rows)

        return self._store.read(read)

    def list_recent(self, limit: int = 200) -> tuple[Question, ...]:
        return self._store.read(
            lambda connection: tuple(
                _question(connection, row)
                for row in connection.execute(
                    "SELECT * FROM questions ORDER BY updated_at DESC, id LIMIT ?", (limit,)
                ).fetchall()
            )
        )

    def counts(self) -> dict[str, int]:
        def read(connection: sqlite3.Connection) -> dict[str, int]:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM questions GROUP BY status"
            ).fetchall()
            counts = {status.value: 0 for status in QuestionStatus}
            counts.update({row["status"]: row["count"] for row in rows})
            return counts

        return self._store.read(read)

    @staticmethod
    def _require_mappings(
        connection: sqlite3.Connection,
        *,
        topic_ids: tuple[str, ...],
        capability_ids: tuple[str, ...],
    ) -> None:
        for topic_id in topic_ids:
            row = connection.execute(
                "SELECT status FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if row is None or row["status"] != "active":
                raise DomainValidationError(f"Unknown or inactive topic ID: {topic_id}")
        for capability_id in capability_ids:
            row = connection.execute(
                "SELECT 1 FROM capability_dimensions WHERE id = ?", (capability_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown capability ID: {capability_id}")

    @staticmethod
    def _insert_version(connection: sqlite3.Connection, version: QuestionVersion) -> None:
        connection.execute(
            """
            INSERT INTO question_versions(
                question_id, version, prompt, intent, rubric_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                version.question_id,
                version.version,
                version.prompt,
                version.intent,
                None
                if version.rubric is None
                else json.dumps(version.rubric, ensure_ascii=False, separators=(",", ":")),
                version.created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO question_version_topics(question_id, question_version, topic_id)
            VALUES (?, ?, ?)
            """,
            ((version.question_id, version.version, item) for item in version.topic_ids),
        )
        connection.executemany(
            """
            INSERT INTO question_version_capabilities(
                question_id, question_version, capability_id
            ) VALUES (?, ?, ?)
            """,
            ((version.question_id, version.version, item) for item in version.capability_ids),
        )
