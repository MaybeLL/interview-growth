"""Persistence for low-confidence memories from real interviews."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from interview_growth.domain.errors import DomainValidationError

from .scoped import GoalScopedStore


class RealInterviewRepository:
    def __init__(self, database_path: Path, goal_id: str) -> None:
        self._store = GoalScopedStore(database_path, goal_id)

    def create(
        self,
        *,
        review_id: str,
        company: str,
        role_title: str,
        round_name: str,
        interviewed_at: str,
        result: str,
        overall_notes: str,
        memories: list[dict[str, Any]],
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO real_interview_reviews(
                    id, company, role_title, round_name, interviewed_at,
                    result, overall_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    company,
                    role_title,
                    round_name,
                    interviewed_at,
                    result,
                    overall_notes,
                    timestamp,
                ),
            )
            for sequence, memory in enumerate(memories, start=1):
                coverage = self._coverage_status(
                    connection,
                    question_id=str(memory["question_id"]),
                    topic_ids=tuple(memory["topic_ids"]),
                    capability_ids=tuple(memory["capability_ids"]),
                )
                connection.execute(
                    """
                    INSERT INTO real_interview_question_memories(
                        id, review_id, sequence_number, prompt, answer_summary,
                        interviewer_feedback, question_id, recall_confidence,
                        coverage_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory["id"],
                        review_id,
                        sequence,
                        memory["prompt"],
                        memory["answer_summary"],
                        memory["interviewer_feedback"],
                        memory["question_id"],
                        memory["recall_confidence"],
                        coverage,
                        timestamp,
                    ),
                )
            self._store.append_audit(
                connection,
                event_type="real_interview_review_created",
                payload={
                    "review_id": review_id,
                    "question_count": len(memories),
                    "evidence_eligible": False,
                },
                timestamp=timestamp,
            )
            return {"review_id": review_id}

        response = self._store.write_idempotent(
            operation_name="real_interview_record",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["review_id"]))

    def get(self, review_id: str) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            review = connection.execute(
                "SELECT * FROM real_interview_reviews WHERE id = ?", (review_id,)
            ).fetchone()
            if review is None:
                raise DomainValidationError("Unknown real interview review ID.")
            memories = connection.execute(
                """
                SELECT * FROM real_interview_question_memories
                WHERE review_id = ? ORDER BY sequence_number
                """,
                (review_id,),
            ).fetchall()
            value = dict(review)
            value["questions"] = [dict(row) for row in memories]
            value["evidence_eligible"] = False
            value["blind_spot_count"] = sum(
                row["coverage_status"] != "mapped" for row in memories
            )
            return value

        return self._store.read(read)

    def list(self, limit: int) -> list[dict[str, Any]]:
        def read(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                """
                SELECT review.*, COUNT(memory.id) AS question_count,
                       SUM(CASE WHEN memory.coverage_status != 'mapped' THEN 1 ELSE 0 END)
                           AS blind_spot_count
                FROM real_interview_reviews AS review
                LEFT JOIN real_interview_question_memories AS memory
                  ON memory.review_id = review.id
                GROUP BY review.id
                ORDER BY review.interviewed_at DESC, review.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._store.read(read)

    @staticmethod
    def _coverage_status(
        connection: sqlite3.Connection,
        *,
        question_id: str,
        topic_ids: tuple[object, ...],
        capability_ids: tuple[object, ...],
    ) -> str:
        if not topic_ids and not capability_ids:
            return "unmapped"
        candidates = connection.execute(
            """
            SELECT DISTINCT question.id
            FROM questions AS question
            JOIN question_versions AS version
              ON version.question_id = question.id
             AND version.version = question.current_version
            LEFT JOIN question_version_topics AS topic
              ON topic.question_id = version.question_id
             AND topic.question_version = version.version
            LEFT JOIN question_version_capabilities AS capability
              ON capability.question_id = version.question_id
             AND capability.question_version = version.version
            WHERE question.status = 'assessable' AND question.id != ?
            """,
            (question_id,),
        ).fetchall()
        if not candidates:
            return "blind_spot"
        candidate_ids = {str(row["id"]) for row in candidates}
        if topic_ids:
            topic_match = connection.execute(
                f"""
                SELECT 1 FROM question_version_topics
                WHERE question_id IN ({','.join('?' for _ in candidate_ids)})
                  AND topic_id IN ({','.join('?' for _ in topic_ids)}) LIMIT 1
                """,
                (*candidate_ids, *topic_ids),
            ).fetchone()
            if topic_match is not None:
                return "mapped"
        if capability_ids:
            capability_match = connection.execute(
                f"""
                SELECT 1 FROM question_version_capabilities
                WHERE question_id IN ({','.join('?' for _ in candidate_ids)})
                  AND capability_id IN ({','.join('?' for _ in capability_ids)}) LIMIT 1
                """,
                (*candidate_ids, *capability_ids),
            ).fetchone()
            if capability_match is not None:
                return "mapped"
        return "blind_spot"
