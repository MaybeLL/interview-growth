"""Evidence, dispute, and training persistence for one isolated goal."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from interview_growth.domain.errors import DomainValidationError

from .scoped import GoalScopedStore, json_object


class CapabilityRepository:
    def __init__(self, database_path: Path, goal_id: str) -> None:
        self._store = GoalScopedStore(database_path, goal_id)

    def current_standard_id(self) -> str:
        def read(connection: sqlite3.Connection) -> str:
            row = connection.execute(
                "SELECT id FROM standard_versions ORDER BY version_number DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise DomainValidationError("An approved target standard is required.")
            return str(row["id"])

        return self._store.read(read)

    def requirements(self, standard_version_id: str) -> list[dict[str, Any]]:
        def read(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                """
                SELECT 'capability' AS subject_type, capability_id AS subject_id,
                       capability_name_snapshot AS subject_name, required_level,
                       weight, critical, minimum_evidence_count
                FROM standard_capability_requirements
                WHERE standard_version_id = ?
                UNION ALL
                SELECT 'topic', topic_id, topic_name_snapshot, required_level,
                       weight, critical, minimum_evidence_count
                FROM standard_topic_requirements
                WHERE standard_version_id = ?
                ORDER BY subject_type, subject_name
                """,
                (standard_version_id, standard_version_id),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._store.read(read)

    def evidence(self, standard_version_id: str) -> list[dict[str, Any]]:
        """Return original dimensions plus dispute/reassessment state."""

        def read(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            originals = connection.execute(
                """
                SELECT evaluation.id AS evaluation_id, evaluation.question_id,
                       evaluation.question_version, evaluation.created_at,
                       evaluation.evidence_eligible, attempt.assistance_level,
                       dimension.capability_id, capability.canonical_name,
                       dimension.level, dimension.confidence, dimension.gaps,
                       dimension.improvement, dispute.id AS dispute_id,
                       dispute.status AS dispute_status,
                       dispute.resolution AS dispute_resolution,
                       reassessment.id AS reassessment_id,
                       reassessment.dimensions_json AS reassessment_dimensions_json,
                       reassessment.evidence_eligible AS reassessment_evidence_eligible,
                       reassessment.created_at AS reassessment_created_at
                FROM evaluations AS evaluation
                JOIN attempts AS attempt ON attempt.id = evaluation.attempt_id
                JOIN dimension_evaluations AS dimension
                  ON dimension.evaluation_id = evaluation.id
                JOIN capability_dimensions AS capability
                  ON capability.id = dimension.capability_id
                LEFT JOIN evaluation_disputes AS dispute
                  ON dispute.evaluation_id = evaluation.id
                LEFT JOIN evaluation_reassessments AS reassessment
                  ON reassessment.dispute_id = dispute.id
                WHERE evaluation.standard_version_id = ?
                ORDER BY evaluation.created_at, evaluation.id
                """,
                (standard_version_id,),
            ).fetchall()
            topic_rows = connection.execute(
                """
                SELECT question_id, question_version, topic_id
                FROM question_version_topics
                """
            ).fetchall()
            topic_names = {
                str(row["id"]): str(row["canonical_name"])
                for row in connection.execute(
                    "SELECT id, canonical_name FROM topics"
                ).fetchall()
            }
            topics_by_question: dict[tuple[str, int], list[tuple[str, str]]] = {}
            for row in topic_rows:
                key = (str(row["question_id"]), int(row["question_version"]))
                topic_id = str(row["topic_id"])
                topics_by_question.setdefault(key, []).append(
                    (topic_id, topic_names[topic_id])
                )

            result: list[dict[str, Any]] = []
            seen_reassessments: set[str] = set()
            for row in originals:
                value = dict(row)
                value["subject_type"] = "capability"
                value["subject_id"] = value.pop("capability_id")
                value["subject_name"] = value.pop("canonical_name")
                value["source"] = "original"
                result.append(value)
                for topic_id, topic_name in topics_by_question.get(
                    (str(row["question_id"]), int(row["question_version"])), []
                ):
                    topic_value = dict(value)
                    topic_value["subject_type"] = "topic"
                    topic_value["subject_id"] = topic_id
                    topic_value["subject_name"] = topic_name
                    result.append(topic_value)

                reassessment_id = row["reassessment_id"]
                if reassessment_id is None or str(reassessment_id) in seen_reassessments:
                    continue
                seen_reassessments.add(str(reassessment_id))
                raw_dimensions = cast(
                    object, json.loads(str(row["reassessment_dimensions_json"]))
                )
                if not isinstance(raw_dimensions, list):
                    raise RuntimeError("Stored reassessment dimensions are invalid.")
                dimension_values = cast(list[object], raw_dimensions)
                for raw_dimension in dimension_values:
                    dimension = raw_dimension
                    if not isinstance(dimension, dict):
                        raise RuntimeError("Stored reassessment dimension is invalid.")
                    dimension = cast(dict[str, Any], dimension)
                    capability_id = str(dimension["capability_id"])
                    capability_row = connection.execute(
                        "SELECT canonical_name FROM capability_dimensions WHERE id = ?",
                        (capability_id,),
                    ).fetchone()
                    if capability_row is None:
                        raise RuntimeError("Reassessment references an unknown capability.")
                    common: dict[str, Any] = {
                        "evaluation_id": str(reassessment_id),
                        "question_id": str(row["question_id"]),
                        "question_version": int(row["question_version"]),
                        "created_at": str(row["reassessment_created_at"]),
                        "evidence_eligible": bool(row["reassessment_evidence_eligible"]),
                        "assistance_level": str(row["assistance_level"]),
                        "level": dimension.get("level"),
                        "confidence": dimension["confidence"],
                        "gaps": dimension["gaps"],
                        "improvement": dimension["improvement"],
                        "dispute_id": str(row["dispute_id"]),
                        "dispute_status": str(row["dispute_status"]),
                        "dispute_resolution": str(row["dispute_resolution"]),
                        "reassessment_id": str(reassessment_id),
                        "source": "reassessment",
                        "subject_type": "capability",
                        "subject_id": capability_id,
                        "subject_name": str(capability_row["canonical_name"]),
                    }
                    result.append(common)
                    for topic_id, topic_name in topics_by_question.get(
                        (str(row["question_id"]), int(row["question_version"])), []
                    ):
                        topic_value = dict(common)
                        topic_value["subject_type"] = "topic"
                        topic_value["subject_id"] = topic_id
                        topic_value["subject_name"] = topic_name
                        result.append(topic_value)
            return result

        return self._store.read(read)

    def create_dispute(
        self,
        *,
        dispute_id: str,
        evaluation_id: str,
        reason: str,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            if connection.execute(
                "SELECT 1 FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone() is None:
                raise DomainValidationError("Unknown evaluation ID.")
            connection.execute(
                """
                INSERT INTO evaluation_disputes(
                    id, evaluation_id, reason, status, created_at
                ) VALUES (?, ?, ?, 'open', ?)
                """,
                (dispute_id, evaluation_id, reason, timestamp),
            )
            self._store.append_audit(
                connection,
                event_type="evaluation_disputed",
                payload={"dispute_id": dispute_id, "evaluation_id": evaluation_id},
                timestamp=timestamp,
            )
            return {"dispute_id": dispute_id}

        response = self._store.write_idempotent(
            operation_name="evaluation_dispute",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_dispute(str(response["dispute_id"]))

    def submit_reassessment(
        self,
        *,
        reassessment_id: str,
        dispute_id: str,
        summary: str,
        dimensions: list[dict[str, Any]],
        provenance: dict[str, object],
        evidence_eligible: bool,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            dispute = connection.execute(
                """
                SELECT dispute.status, evaluation.question_id, evaluation.question_version
                FROM evaluation_disputes AS dispute
                JOIN evaluations AS evaluation ON evaluation.id = dispute.evaluation_id
                WHERE dispute.id = ?
                """,
                (dispute_id,),
            ).fetchone()
            if dispute is None or dispute["status"] != "open":
                raise DomainValidationError("Reassessment requires an open dispute.")
            mapped = {
                str(row["capability_id"])
                for row in connection.execute(
                    """
                    SELECT capability_id FROM question_version_capabilities
                    WHERE question_id = ? AND question_version = ?
                    """,
                    (dispute["question_id"], dispute["question_version"]),
                ).fetchall()
            }
            submitted = {str(item["capability_id"]) for item in dimensions}
            if not submitted or not submitted <= mapped:
                raise DomainValidationError(
                    "Reassessment dimensions must match the frozen question."
                )
            connection.execute(
                """
                INSERT INTO evaluation_reassessments(
                    id, dispute_id, summary, dimensions_json,
                    evaluator_provenance_json, evidence_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reassessment_id,
                    dispute_id,
                    summary,
                    json.dumps(dimensions, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(provenance, ensure_ascii=False, separators=(",", ":")),
                    int(evidence_eligible),
                    timestamp,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="evaluation_reassessed",
                payload={"dispute_id": dispute_id, "reassessment_id": reassessment_id},
                timestamp=timestamp,
            )
            return {"dispute_id": dispute_id}

        response = self._store.write_idempotent(
            operation_name="evaluation_submit_reassessment",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_dispute(str(response["dispute_id"]))

    def resolve_dispute(
        self,
        *,
        dispute_id: str,
        resolution: str,
        notes: str,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            dispute = connection.execute(
                "SELECT status FROM evaluation_disputes WHERE id = ?", (dispute_id,)
            ).fetchone()
            if dispute is None or dispute["status"] != "open":
                raise DomainValidationError("Only an open dispute can be resolved.")
            if resolution == "reassessment" and connection.execute(
                "SELECT 1 FROM evaluation_reassessments WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone() is None:
                raise DomainValidationError("No reassessment has been submitted.")
            connection.execute(
                """
                UPDATE evaluation_disputes
                SET status = 'resolved', resolution = ?, resolution_notes = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolution, notes, timestamp, dispute_id),
            )
            self._store.append_audit(
                connection,
                event_type="evaluation_dispute_resolved",
                payload={"dispute_id": dispute_id, "resolution": resolution},
                timestamp=timestamp,
            )
            return {"dispute_id": dispute_id}

        response = self._store.write_idempotent(
            operation_name="evaluation_resolve_dispute",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_dispute(str(response["dispute_id"]))

    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                """
                SELECT dispute.*, reassessment.id AS reassessment_id,
                       reassessment.summary AS reassessment_summary,
                       reassessment.created_at AS reassessment_created_at
                FROM evaluation_disputes AS dispute
                LEFT JOIN evaluation_reassessments AS reassessment
                  ON reassessment.dispute_id = dispute.id
                WHERE dispute.id = ?
                """,
                (dispute_id,),
            ).fetchone()
            if row is None:
                raise DomainValidationError("Unknown dispute ID.")
            return dict(row)

        return self._store.read(read)

    def create_prescription(
        self,
        *,
        prescription_id: str,
        subject_type: str,
        subject_id: str,
        gap_snapshot: dict[str, object],
        action_plan: str,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO training_prescriptions(
                    id, subject_type, subject_id, gap_snapshot_json,
                    action_plan, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    prescription_id,
                    subject_type,
                    subject_id,
                    json.dumps(gap_snapshot, ensure_ascii=False, separators=(",", ":")),
                    action_plan,
                    timestamp,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="training_prescription_created",
                payload={"prescription_id": prescription_id, "subject_id": subject_id},
                timestamp=timestamp,
            )
            return {"prescription_id": prescription_id}

        response = self._store.write_idempotent(
            operation_name="prescription_create",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_prescription(str(response["prescription_id"]))

    def get_prescription(self, prescription_id: str) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT * FROM training_prescriptions WHERE id = ?", (prescription_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("Unknown prescription ID.")
            value = dict(row)
            value["gap_snapshot"] = json_object(value.pop("gap_snapshot_json"))
            return value

        return self._store.read(read)

    def next_prescription(self) -> dict[str, Any] | None:
        identifier = self._store.read(
            lambda connection: (
                lambda row: None if row is None else str(row["id"])
            )(
                connection.execute(
                    """
                    SELECT id FROM training_prescriptions
                    WHERE status = 'active' ORDER BY created_at LIMIT 1
                    """
                ).fetchone()
            )
        )
        return None if identifier is None else self.get_prescription(identifier)

    def schedule_retest(
        self,
        *,
        retest_id: str,
        prescription_id: str,
        question_id: str,
        question_version: int,
        due_at: str,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            prescription = connection.execute(
                "SELECT * FROM training_prescriptions WHERE id = ?",
                (prescription_id,),
            ).fetchone()
            if prescription is None or prescription["status"] != "active":
                raise DomainValidationError("Retest requires an active prescription.")
            mapping_table = (
                "question_version_capabilities"
                if prescription["subject_type"] == "capability"
                else "question_version_topics"
            )
            mapping_column = (
                "capability_id" if prescription["subject_type"] == "capability" else "topic_id"
            )
            mapped = connection.execute(
                f"""
                SELECT 1 FROM {mapping_table}
                WHERE question_id = ? AND question_version = ? AND {mapping_column} = ?
                """,
                (question_id, question_version, prescription["subject_id"]),
            ).fetchone()
            if mapped is None:
                raise DomainValidationError("Retest question does not cover the prescribed gap.")
            used = connection.execute(
                """
                SELECT 1 FROM evaluations
                WHERE question_id = ? AND evidence_eligible = 1 LIMIT 1
                """,
                (question_id,),
            ).fetchone()
            if used is not None:
                raise DomainValidationError(
                    "A retest must use a different question from prior eligible evidence."
                )
            connection.execute(
                """
                INSERT INTO retest_schedules(
                    id, prescription_id, question_id, question_version,
                    due_at, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'scheduled', ?)
                """,
                (retest_id, prescription_id, question_id, question_version, due_at, timestamp),
            )
            self._store.append_audit(
                connection,
                event_type="retest_scheduled",
                payload={"retest_id": retest_id, "prescription_id": prescription_id},
                timestamp=timestamp,
            )
            return {"retest_id": retest_id}

        response = self._store.write_idempotent(
            operation_name="retest_schedule",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_retest(str(response["retest_id"]))

    def get_retest(self, retest_id: str) -> dict[str, Any]:
        def read(connection: sqlite3.Connection) -> dict[str, Any]:
            row = connection.execute(
                "SELECT * FROM retest_schedules WHERE id = ?", (retest_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("Unknown retest ID.")
            return dict(row)

        return self._store.read(read)
