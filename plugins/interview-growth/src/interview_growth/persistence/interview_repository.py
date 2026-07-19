"""Persistence for interview state, raw attempts, evaluations, and practice."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from interview_growth.domain.errors import DomainValidationError, VersionConflictError
from interview_growth.domain.models import (
    AssistanceLevel,
    Attempt,
    DimensionEvaluation,
    DimensionEvaluationInput,
    Evaluation,
    InterviewItem,
    InterviewItemKind,
    InterviewItemStatus,
    InterviewSession,
    InterviewStatus,
    PracticeRecord,
)

from .scoped import GoalScopedStore, json_object


def _item(row: sqlite3.Row) -> InterviewItem:
    return InterviewItem(
        id=row["id"],
        interview_id=row["interview_id"],
        question_id=row["question_id"],
        question_version=row["question_version"],
        kind=InterviewItemKind(row["kind"]),
        parent_item_id=row["parent_item_id"],
        trigger_attempt_id=row["trigger_attempt_id"],
        sequence_number=row["sequence_number"],
        status=InterviewItemStatus(row["status"]),
        registered_at=row["registered_at"],
    )


def _attempt(row: sqlite3.Row) -> Attempt:
    return Attempt(
        id=row["id"],
        interview_id=row["interview_id"],
        interview_item_id=row["interview_item_id"],
        question_id=row["question_id"],
        question_version=row["question_version"],
        answer_text=row["answer_text"],
        assistance_level=AssistanceLevel(row["assistance_level"]),
        recorded_at=row["recorded_at"],
    )


class InterviewRepository:
    def __init__(self, database_path: Path, goal_id: str) -> None:
        self._store = GoalScopedStore(database_path, goal_id)

    def start(
        self,
        *,
        interview_id: str,
        host_session_id: str,
        standard_version_id: str,
        plan: dict[str, object],
        items: tuple[InterviewItem, ...],
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InterviewSession:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            if connection.execute(
                "SELECT 1 FROM standard_versions WHERE id = ?", (standard_version_id,)
            ).fetchone() is None:
                raise DomainValidationError("An approved target standard is required.")
            active = connection.execute(
                """
                SELECT id FROM interview_sessions
                WHERE status IN ('in_progress', 'paused') LIMIT 1
                """
            ).fetchone()
            if active is not None:
                raise DomainValidationError(
                    f"Interview {active['id']} is already active for this goal."
                )
            connection.execute(
                """
                INSERT INTO interview_sessions(
                    id, created_host_session_id, status, standard_version_id,
                    plan_json, revision, started_at, updated_at
                ) VALUES (?, ?, 'in_progress', ?, ?, 1, ?, ?)
                """,
                (
                    interview_id,
                    host_session_id,
                    standard_version_id,
                    json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    timestamp,
                ),
            )
            for item in items:
                self._require_assessable_version(
                    connection, item.question_id, item.question_version
                )
                self._insert_item(connection, item)
            self._append_checkpoint(
                connection,
                checkpoint_id=f"{interview_id}:start",
                interview_id=interview_id,
                revision=1,
                reason="interview_started",
                timestamp=timestamp,
            )
            self._store.append_audit(
                connection,
                event_type="interview_started",
                payload={
                    "interview_id": interview_id,
                    "standard_version_id": standard_version_id,
                    "question_count": len(items),
                },
                timestamp=timestamp,
            )
            return {"interview_id": interview_id}

        response = self._store.write_idempotent(
            operation_name="interview_start",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["interview_id"]))

    def register_item(
        self,
        *,
        item: InterviewItem,
        expected_revision: int,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InterviewSession:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            session = self._require_session_revision(
                connection, item.interview_id, expected_revision
            )
            if session["status"] != InterviewStatus.IN_PROGRESS.value:
                raise DomainValidationError("Questions can only be added to an active interview.")
            self._require_assessable_version(
                connection, item.question_id, item.question_version
            )
            if item.kind is InterviewItemKind.FOLLOWUP:
                self._require_followup_links(connection, item)
            self._insert_item(connection, item)
            self._increment_revision(
                connection, item.interview_id, expected_revision, timestamp
            )
            self._store.append_audit(
                connection,
                event_type="interview_question_registered",
                payload={
                    "interview_id": item.interview_id,
                    "item_id": item.id,
                    "kind": item.kind.value,
                    "question_id": item.question_id,
                    "question_version": item.question_version,
                },
                timestamp=timestamp,
            )
            return {"interview_id": item.interview_id}

        response = self._store.write_idempotent(
            operation_name=(
                "followup_register"
                if item.kind is InterviewItemKind.FOLLOWUP
                else "interview_register_question"
            ),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["interview_id"]))

    def record_attempt(
        self,
        *,
        attempt: Attempt,
        expected_revision: int,
        checkpoint_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Attempt:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            session = self._require_session_revision(
                connection, attempt.interview_id, expected_revision
            )
            if session["status"] != InterviewStatus.IN_PROGRESS.value:
                raise DomainValidationError("Answers can only be recorded in an active interview.")
            item = connection.execute(
                "SELECT * FROM interview_items WHERE id = ? AND interview_id = ?",
                (attempt.interview_item_id, attempt.interview_id),
            ).fetchone()
            if item is None:
                raise DomainValidationError("Unknown interview question item.")
            if item["status"] != InterviewItemStatus.QUEUED.value:
                raise DomainValidationError("This interview question already has an answer.")
            if (
                item["question_id"] != attempt.question_id
                or item["question_version"] != attempt.question_version
            ):
                raise RuntimeError("Attempt does not reference the frozen interview question.")
            connection.execute(
                """
                INSERT INTO attempts(
                    id, interview_id, interview_item_id, question_id, question_version,
                    answer_text, assistance_level, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.id,
                    attempt.interview_id,
                    attempt.interview_item_id,
                    attempt.question_id,
                    attempt.question_version,
                    attempt.answer_text,
                    attempt.assistance_level.value,
                    attempt.recorded_at,
                ),
            )
            connection.execute(
                "UPDATE interview_items SET status = 'answered' WHERE id = ?",
                (attempt.interview_item_id,),
            )
            new_revision = self._increment_revision(
                connection,
                attempt.interview_id,
                expected_revision,
                attempt.recorded_at,
            )
            self._append_checkpoint(
                connection,
                checkpoint_id=checkpoint_id,
                interview_id=attempt.interview_id,
                revision=new_revision,
                reason="raw_attempt_recorded",
                timestamp=attempt.recorded_at,
            )
            self._store.append_audit(
                connection,
                event_type="attempt_recorded",
                payload={
                    "attempt_id": attempt.id,
                    "interview_id": attempt.interview_id,
                    "assistance_level": attempt.assistance_level.value,
                },
                timestamp=attempt.recorded_at,
            )
            return {"attempt_id": attempt.id}

        response = self._store.write_idempotent(
            operation_name="attempt_record",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=attempt.recorded_at,
            operation=write,
        )
        return self.get_attempt(str(response["attempt_id"]))

    def submit_evaluation(
        self,
        *,
        evaluation: Evaluation,
        dimension_inputs: tuple[DimensionEvaluationInput, ...],
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
    ) -> Evaluation:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            session = self._require_session_revision(
                connection, evaluation.interview_id, expected_revision
            )
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE id = ? AND interview_id = ?",
                (evaluation.attempt_id, evaluation.interview_id),
            ).fetchone()
            if attempt is None:
                raise DomainValidationError("Evaluation requires a recorded raw attempt.")
            item = connection.execute(
                "SELECT status FROM interview_items WHERE id = ?",
                (attempt["interview_item_id"],),
            ).fetchone()
            if item is None or item["status"] != InterviewItemStatus.ANSWERED.value:
                raise DomainValidationError("This attempt is not awaiting evaluation.")
            if session["standard_version_id"] != evaluation.standard_version_id:
                raise RuntimeError("Evaluation does not use the interview's frozen standard.")
            if (
                attempt["question_id"] != evaluation.question_id
                or attempt["question_version"] != evaluation.question_version
            ):
                raise RuntimeError("Evaluation does not use the attempt's frozen question.")
            mapped_capabilities = {
                row["capability_id"]
                for row in connection.execute(
                    """
                    SELECT capability_id FROM question_version_capabilities
                    WHERE question_id = ? AND question_version = ?
                    """,
                    (evaluation.question_id, evaluation.question_version),
                ).fetchall()
            }
            submitted = {item.capability_id for item in dimension_inputs}
            if not submitted or not submitted <= mapped_capabilities:
                raise DomainValidationError(
                    "Dimension evaluations must reference capabilities mapped to the question."
                )
            connection.execute(
                """
                INSERT INTO evaluations(
                    id, attempt_id, interview_id, standard_version_id, question_id,
                    question_version, summary, evaluator_provenance_json,
                    evidence_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.id,
                    evaluation.attempt_id,
                    evaluation.interview_id,
                    evaluation.standard_version_id,
                    evaluation.question_id,
                    evaluation.question_version,
                    evaluation.summary,
                    json.dumps(
                        evaluation.evaluator_provenance,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    int(evaluation.evidence_eligible),
                    evaluation.created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO dimension_evaluations(
                    evaluation_id, capability_id, level, evidence, gaps,
                    improvement, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        evaluation.id,
                        value.capability_id,
                        value.level,
                        value.evidence,
                        value.gaps,
                        value.improvement,
                        value.confidence,
                    )
                    for value in dimension_inputs
                ),
            )
            connection.execute(
                "UPDATE interview_items SET status = 'evaluated' WHERE id = ?",
                (attempt["interview_item_id"],),
            )
            self._increment_revision(
                connection,
                evaluation.interview_id,
                expected_revision,
                evaluation.created_at,
            )
            self._store.append_audit(
                connection,
                event_type="evaluation_submitted",
                payload={
                    "evaluation_id": evaluation.id,
                    "attempt_id": evaluation.attempt_id,
                    "evidence_eligible": evaluation.evidence_eligible,
                },
                timestamp=evaluation.created_at,
            )
            return {"evaluation_id": evaluation.id}

        response = self._store.write_idempotent(
            operation_name="evaluation_submit",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=evaluation.created_at,
            operation=write,
        )
        return self.get_evaluation(str(response["evaluation_id"]))

    def checkpoint(
        self,
        *,
        interview_id: str,
        checkpoint_id: str,
        expected_revision: int,
        reason: str,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InterviewSession:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            self._require_session_revision(connection, interview_id, expected_revision)
            self._append_checkpoint(
                connection,
                checkpoint_id=checkpoint_id,
                interview_id=interview_id,
                revision=expected_revision,
                reason=reason,
                timestamp=timestamp,
            )
            return {"interview_id": interview_id}

        response = self._store.write_idempotent(
            operation_name="interview_checkpoint",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["interview_id"]))

    def transition(
        self,
        *,
        interview_id: str,
        expected_revision: int,
        requested: InterviewStatus,
        timestamp: str,
        outcome_summary: str | None,
        idempotency_key: str,
        request_hash: str,
    ) -> InterviewSession:
        operation_name = f"interview_{requested.value}"

        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            row = self._require_session_revision(connection, interview_id, expected_revision)
            current = InterviewStatus(row["status"])
            allowed: dict[InterviewStatus, set[InterviewStatus]] = {
                InterviewStatus.IN_PROGRESS: {
                    InterviewStatus.PAUSED,
                    InterviewStatus.COMPLETED,
                    InterviewStatus.ABORTED,
                },
                InterviewStatus.PAUSED: {
                    InterviewStatus.IN_PROGRESS,
                    InterviewStatus.COMPLETED,
                    InterviewStatus.ABORTED,
                },
                InterviewStatus.COMPLETED: set(),
                InterviewStatus.ABORTED: set(),
            }
            if requested not in allowed[current]:
                raise DomainValidationError(
                    f"Cannot transition interview from {current.value} to {requested.value}."
                )
            paused_at = timestamp if requested is InterviewStatus.PAUSED else None
            completed_at = (
                timestamp
                if requested in {InterviewStatus.COMPLETED, InterviewStatus.ABORTED}
                else None
            )
            connection.execute(
                """
                UPDATE interview_sessions
                SET status = ?, revision = revision + 1, updated_at = ?,
                    paused_at = ?, completed_at = ?, outcome_summary = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    requested.value,
                    timestamp,
                    paused_at,
                    completed_at,
                    outcome_summary,
                    interview_id,
                    expected_revision,
                ),
            )
            if requested in {InterviewStatus.COMPLETED, InterviewStatus.ABORTED}:
                connection.execute(
                    """
                    UPDATE interview_items SET status = 'skipped'
                    WHERE interview_id = ? AND status = 'queued'
                    """,
                    (interview_id,),
                )
            self._append_checkpoint(
                connection,
                checkpoint_id=f"{interview_id}:{requested.value}:{expected_revision + 1}",
                interview_id=interview_id,
                revision=expected_revision + 1,
                reason=operation_name,
                timestamp=timestamp,
            )
            self._store.append_audit(
                connection,
                event_type=operation_name,
                payload={"interview_id": interview_id},
                timestamp=timestamp,
            )
            return {"interview_id": interview_id}

        response = self._store.write_idempotent(
            operation_name=operation_name,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get(str(response["interview_id"]))

    def record_practice(
        self,
        *,
        record: PracticeRecord,
        idempotency_key: str,
        request_hash: str,
    ) -> PracticeRecord:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            if connection.execute(
                """
                SELECT 1 FROM question_versions WHERE question_id = ? AND version = ?
                """,
                (record.question_id, record.question_version),
            ).fetchone() is None:
                raise DomainValidationError("Unknown practice question version.")
            connection.execute(
                """
                INSERT INTO practice_records(
                    id, question_id, question_version, response_text,
                    assistance_level, coach_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.question_id,
                    record.question_version,
                    record.response_text,
                    record.assistance_level.value,
                    record.coach_notes,
                    record.created_at,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="practice_recorded",
                payload={"practice_id": record.id, "evidence_eligible": False},
                timestamp=record.created_at,
            )
            return {"practice_id": record.id}

        response = self._store.write_idempotent(
            operation_name="practice_record",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=record.created_at,
            operation=write,
        )
        return self.get_practice(str(response["practice_id"]))

    def get(self, interview_id: str) -> InterviewSession:
        def read(connection: sqlite3.Connection) -> InterviewSession:
            row = connection.execute(
                "SELECT * FROM interview_sessions WHERE id = ?", (interview_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown interview ID: {interview_id}")
            items = connection.execute(
                """
                SELECT * FROM interview_items
                WHERE interview_id = ? ORDER BY sequence_number
                """,
                (interview_id,),
            ).fetchall()
            return InterviewSession(
                id=row["id"],
                status=InterviewStatus(row["status"]),
                standard_version_id=row["standard_version_id"],
                plan=json_object(row["plan_json"]),
                revision=row["revision"],
                started_at=row["started_at"],
                updated_at=row["updated_at"],
                paused_at=row["paused_at"],
                completed_at=row["completed_at"],
                outcome_summary=row["outcome_summary"],
                items=tuple(_item(item) for item in items),
            )

        return self._store.read(read)

    def find_active(self) -> InterviewSession | None:
        identifier = self._store.read(
            lambda connection: (
                lambda row: None if row is None else str(row["id"])
            )(
                connection.execute(
                    """
                    SELECT id FROM interview_sessions
                    WHERE status IN ('in_progress', 'paused')
                    ORDER BY updated_at DESC LIMIT 1
                    """
                ).fetchone()
            )
        )
        return None if identifier is None else self.get(identifier)

    def get_attempt(self, attempt_id: str) -> Attempt:
        def read(connection: sqlite3.Connection) -> Attempt:
            row = connection.execute(
                "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown attempt ID: {attempt_id}")
            return _attempt(row)

        return self._store.read(read)

    def get_evaluation(self, evaluation_id: str) -> Evaluation:
        def read(connection: sqlite3.Connection) -> Evaluation:
            row = connection.execute(
                "SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown evaluation ID: {evaluation_id}")
            dimensions = connection.execute(
                """
                SELECT dimension.*, capability.canonical_name
                FROM dimension_evaluations AS dimension
                JOIN capability_dimensions AS capability
                  ON capability.id = dimension.capability_id
                WHERE dimension.evaluation_id = ? ORDER BY capability.normalized_name
                """,
                (evaluation_id,),
            ).fetchall()
            return Evaluation(
                id=row["id"],
                attempt_id=row["attempt_id"],
                interview_id=row["interview_id"],
                standard_version_id=row["standard_version_id"],
                question_id=row["question_id"],
                question_version=row["question_version"],
                summary=row["summary"],
                evaluator_provenance=json_object(row["evaluator_provenance_json"]),
                evidence_eligible=bool(row["evidence_eligible"]),
                created_at=row["created_at"],
                dimensions=tuple(
                    DimensionEvaluation(
                        capability_id=item["capability_id"],
                        capability_name=item["canonical_name"],
                        level=item["level"],
                        evidence=item["evidence"],
                        gaps=item["gaps"],
                        improvement=item["improvement"],
                        confidence=item["confidence"],
                    )
                    for item in dimensions
                ),
            )

        return self._store.read(read)

    def find_evaluation_for_attempt(self, attempt_id: str) -> Evaluation | None:
        identifier = self._store.read(
            lambda connection: (
                lambda row: None if row is None else str(row["id"])
            )(
                connection.execute(
                    "SELECT id FROM evaluations WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
            )
        )
        return None if identifier is None else self.get_evaluation(identifier)

    def get_practice(self, practice_id: str) -> PracticeRecord:
        def read(connection: sqlite3.Connection) -> PracticeRecord:
            row = connection.execute(
                "SELECT * FROM practice_records WHERE id = ?", (practice_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown practice ID: {practice_id}")
            return PracticeRecord(
                id=row["id"],
                question_id=row["question_id"],
                question_version=row["question_version"],
                response_text=row["response_text"],
                assistance_level=AssistanceLevel(row["assistance_level"]),
                coach_notes=row["coach_notes"],
                created_at=row["created_at"],
            )

        return self._store.read(read)

    @staticmethod
    def _require_session_revision(
        connection: sqlite3.Connection,
        interview_id: str,
        expected_revision: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM interview_sessions WHERE id = ?", (interview_id,)
        ).fetchone()
        if row is None:
            raise DomainValidationError(f"Unknown interview ID: {interview_id}")
        if row["revision"] != expected_revision:
            raise VersionConflictError("Interview state changed; reload and retry.")
        return row

    @staticmethod
    def _require_assessable_version(
        connection: sqlite3.Connection,
        question_id: str,
        question_version: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT rubric_json FROM question_versions
            WHERE question_id = ? AND version = ?
            """,
            (question_id, question_version),
        ).fetchone()
        if row is None or row["rubric_json"] is None:
            raise DomainValidationError("Formal interviews require an assessable question version.")

    @staticmethod
    def _insert_item(connection: sqlite3.Connection, item: InterviewItem) -> None:
        connection.execute(
            """
            INSERT INTO interview_items(
                id, interview_id, question_id, question_version, kind,
                parent_item_id, trigger_attempt_id, sequence_number, status, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.interview_id,
                item.question_id,
                item.question_version,
                item.kind.value,
                item.parent_item_id,
                item.trigger_attempt_id,
                item.sequence_number,
                item.status.value,
                item.registered_at,
            ),
        )

    @staticmethod
    def _require_followup_links(
        connection: sqlite3.Connection,
        item: InterviewItem,
    ) -> None:
        parent = connection.execute(
            "SELECT interview_id FROM interview_items WHERE id = ?",
            (item.parent_item_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT interview_id, interview_item_id FROM attempts WHERE id = ?",
            (item.trigger_attempt_id,),
        ).fetchone()
        if (
            parent is None
            or attempt is None
            or parent["interview_id"] != item.interview_id
            or attempt["interview_id"] != item.interview_id
            or attempt["interview_item_id"] != item.parent_item_id
        ):
            raise DomainValidationError(
                "A follow-up must reference its parent item and triggering attempt."
            )

    @staticmethod
    def _increment_revision(
        connection: sqlite3.Connection,
        interview_id: str,
        expected_revision: int,
        timestamp: str,
    ) -> int:
        cursor = connection.execute(
            """
            UPDATE interview_sessions SET revision = revision + 1, updated_at = ?
            WHERE id = ? AND revision = ?
            """,
            (timestamp, interview_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise VersionConflictError("Interview state changed; reload and retry.")
        return expected_revision + 1

    @staticmethod
    def _append_checkpoint(
        connection: sqlite3.Connection,
        *,
        checkpoint_id: str,
        interview_id: str,
        revision: int,
        reason: str,
        timestamp: str,
    ) -> None:
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM interview_items
                WHERE interview_id = ? GROUP BY status
                """,
                (interview_id,),
            ).fetchall()
        }
        connection.execute(
            """
            INSERT INTO interview_checkpoints(
                id, interview_id, interview_revision, state_json, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                interview_id,
                revision,
                json.dumps({"item_counts": counts}, separators=(",", ":")),
                reason,
                timestamp,
            ),
        )
