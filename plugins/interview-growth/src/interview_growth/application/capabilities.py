"""Evidence-backed capability dashboard, disputes, and training prescriptions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import DimensionEvaluationInput
from interview_growth.domain.validation import new_id, request_hash, require_text
from interview_growth.persistence.capability_repository import CapabilityRepository

_PROVENANCE_FIELDS = {"evaluator", "host", "model", "prompt_version"}
_RESOLUTIONS = {"original", "reassessment", "withdrawn"}


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _weighted_median(values: list[tuple[float, float]]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    boundary = total / 2
    accumulated = 0.0
    for level, weight in ordered:
        accumulated += weight
        if accumulated >= boundary:
            return level
    return ordered[-1][0]


class CapabilityService:
    """Expose explainable readiness without collapsing evidence into a fake score."""

    def __init__(
        self,
        goals: GoalService,
        *,
        clock: Callable[[], str] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        self._goals = goals
        self._clock = clock
        self._id_factory = id_factory

    def dashboard(self, *, session_id: str) -> dict[str, Any]:
        repository = self._repository(session_id)
        standard_id = repository.current_standard_id()
        requirements = repository.requirements(standard_id)
        raw_evidence = repository.evidence(standard_id)
        effective = self._effective_evidence(raw_evidence)
        generated_at = self._clock()
        now = _parse_timestamp(generated_at)
        snapshots = [
            self._snapshot(requirement, effective, now) for requirement in requirements
        ]
        critical_blockers = [
            item
            for item in snapshots
            if item["critical"] and item["status"] != "meets"
        ]
        insufficient = [
            item
            for item in snapshots
            if item["status"] in {"no_evidence", "insufficient", "needs_revalidation"}
        ]
        below = [item for item in snapshots if item["status"] == "below"]
        if insufficient:
            readiness = "evidence_insufficient"
        elif critical_blockers or below:
            readiness = "not_ready"
        else:
            readiness = "ready"
        gaps = [
            {
                "subject_type": item["subject_type"],
                "subject_id": item["subject_id"],
                "subject_name": item["subject_name"],
                "status": item["status"],
                "required_level": item["required_level"],
                "current_level": item["current_level"],
                "critical": item["critical"],
                "next_action": self._next_action(item),
            }
            for item in snapshots
            if item["status"] != "meets"
        ]
        unresolved_disputes = len(
            {
                str(item["dispute_id"])
                for item in raw_evidence
                if item.get("dispute_status") == "open"
            }
        )
        result: dict[str, Any] = {
            "standard_version_id": standard_id,
            "generated_at": generated_at,
            "readiness": readiness,
            "readiness_rule": (
                "All critical requirements need sufficient, recent, passing evidence; "
                "all other requirements must also meet their target."
            ),
            "summary": {
                "requirements": len(snapshots),
                "meets": sum(item["status"] == "meets" for item in snapshots),
                "critical_blockers": len(critical_blockers),
                "evidence_gaps": len(insufficient),
                "level_gaps": len(below),
                "unresolved_disputes": unresolved_disputes,
            },
            "requirements": snapshots,
            "gaps": gaps,
            "current_prescription": repository.next_prescription(),
        }
        result["markdown"] = self._render_markdown(result)
        return result

    def evidence(self, *, session_id: str) -> dict[str, Any]:
        repository = self._repository(session_id)
        standard_id = repository.current_standard_id()
        effective = self._effective_evidence(repository.evidence(standard_id))
        return {
            "standard_version_id": standard_id,
            "eligibility_rule": (
                "Independent, complete, confidence >= 0.5, current-standard evidence only; "
                "open disputes and non-selected reassessments are excluded."
            ),
            "evidence": effective,
        }

    def gaps(self, *, session_id: str) -> list[dict[str, Any]]:
        value = self.dashboard(session_id=session_id)["gaps"]
        if not isinstance(value, list):
            raise RuntimeError("Dashboard gaps are invalid.")
        return cast(list[dict[str, Any]], value)

    def dispute(
        self,
        *,
        session_id: str,
        evaluation_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_reason = require_text(reason, field="Dispute reason", maximum=10_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        return self._repository(session_id).create_dispute(
            dispute_id=self._id_factory(),
            evaluation_id=evaluation_id,
            reason=clean_reason,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {"evaluation_id": evaluation_id, "reason": clean_reason}
            ),
        )

    def submit_reassessment(
        self,
        *,
        session_id: str,
        dispute_id: str,
        summary: str,
        dimensions: Sequence[DimensionEvaluationInput],
        evaluator_provenance: Mapping[str, object],
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_summary = require_text(summary, field="Reassessment summary", maximum=10_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        provenance = dict(evaluator_provenance)
        missing = _PROVENANCE_FIELDS - provenance.keys()
        if missing:
            raise DomainValidationError(
                f"Evaluator provenance is missing: {', '.join(sorted(missing))}."
            )
        payload: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for item in dimensions:
            if item.capability_id in identifiers:
                raise DomainValidationError("A capability can only be reassessed once.")
            identifiers.add(item.capability_id)
            if item.level is not None and not 0 <= item.level <= 4:
                raise DomainValidationError("Reassessment level must be between 0 and 4.")
            if not 0 <= item.confidence <= 1:
                raise DomainValidationError("Reassessment confidence must be between 0 and 1.")
            payload.append(
                {
                    "capability_id": item.capability_id,
                    "level": item.level,
                    "evidence": item.evidence,
                    "gaps": item.gaps,
                    "improvement": item.improvement,
                    "confidence": item.confidence,
                }
            )
        if not payload:
            raise DomainValidationError("At least one reassessment dimension is required.")
        eligible = all(item["level"] is not None for item in payload) and all(
            float(item["confidence"]) >= 0.5 for item in payload
        )
        timestamp = self._clock()
        return self._repository(session_id).submit_reassessment(
            reassessment_id=self._id_factory(),
            dispute_id=dispute_id,
            summary=clean_summary,
            dimensions=payload,
            provenance=provenance,
            evidence_eligible=eligible,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "dispute_id": dispute_id,
                    "summary": clean_summary,
                    "dimensions": payload,
                    "evaluator_provenance": provenance,
                }
            ),
        )

    def resolve_dispute(
        self,
        *,
        session_id: str,
        dispute_id: str,
        resolution: str,
        notes: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if resolution not in _RESOLUTIONS:
            raise DomainValidationError(
                "Resolution must be original, reassessment, or withdrawn."
            )
        clean_notes = require_text(notes, field="Resolution notes", maximum=10_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        return self._repository(session_id).resolve_dispute(
            dispute_id=dispute_id,
            resolution=resolution,
            notes=clean_notes,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {"dispute_id": dispute_id, "resolution": resolution, "notes": clean_notes}
            ),
        )

    def create_prescription(
        self,
        *,
        session_id: str,
        subject_type: str,
        subject_id: str,
        action_plan: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if subject_type not in {"topic", "capability"}:
            raise DomainValidationError("Prescription subject must be topic or capability.")
        clean_plan = require_text(action_plan, field="Action plan", maximum=20_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        gap = next(
            (
                item
                for item in self.gaps(session_id=session_id)
                if item["subject_type"] == subject_type and item["subject_id"] == subject_id
            ),
            None,
        )
        if gap is None:
            raise DomainValidationError("The selected subject has no current readiness gap.")
        timestamp = self._clock()
        return self._repository(session_id).create_prescription(
            prescription_id=self._id_factory(),
            subject_type=subject_type,
            subject_id=subject_id,
            gap_snapshot=gap,
            action_plan=clean_plan,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "action_plan": clean_plan,
                    "gap_snapshot": gap,
                }
            ),
        )

    def next_prescription(self, *, session_id: str) -> dict[str, Any] | None:
        return self._repository(session_id).next_prescription()

    def schedule_retest(
        self,
        *,
        session_id: str,
        prescription_id: str,
        question_id: str,
        due_at: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_due_at = require_text(due_at, field="Retest due time", maximum=100)
        _parse_timestamp(clean_due_at)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        _, database_path = self._goals.resolve_current_goal_database(session_id=session_id)
        repository = self._repository(session_id)
        from interview_growth.persistence.question_repository import QuestionRepository

        goal = self._goals.get_current_goal(session_id=session_id)
        question = QuestionRepository(database_path, goal.id).get(question_id)
        timestamp = self._clock()
        return repository.schedule_retest(
            retest_id=self._id_factory(),
            prescription_id=prescription_id,
            question_id=question.id,
            question_version=question.current_version,
            due_at=clean_due_at,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "prescription_id": prescription_id,
                    "question_id": question.id,
                    "question_version": question.current_version,
                    "due_at": clean_due_at,
                }
            ),
        )

    def _repository(self, session_id: str) -> CapabilityRepository:
        goal, database_path = self._goals.resolve_current_goal_database(
            session_id=session_id
        )
        return CapabilityRepository(database_path, goal.id)

    @staticmethod
    def _effective_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        effective: list[dict[str, Any]] = []
        for row in rows:
            if not row["evidence_eligible"] or row["assistance_level"] != "independent":
                continue
            dispute_status = row.get("dispute_status")
            resolution = row.get("dispute_resolution")
            source = row["source"]
            selected = (
                (dispute_status is None and source == "original")
                or (
                    dispute_status == "resolved"
                    and resolution in {"original", "withdrawn"}
                    and source == "original"
                )
                or (
                    dispute_status == "resolved"
                    and resolution == "reassessment"
                    and source == "reassessment"
                )
            )
            if selected and row["level"] is not None and float(row["confidence"]) >= 0.5:
                effective.append(
                    {
                        "evaluation_id": row["evaluation_id"],
                        "source": source,
                        "subject_type": row["subject_type"],
                        "subject_id": row["subject_id"],
                        "subject_name": row["subject_name"],
                        "question_id": row["question_id"],
                        "question_version": row["question_version"],
                        "level": row["level"],
                        "confidence": row["confidence"],
                        "gaps": row["gaps"],
                        "improvement": row["improvement"],
                        "created_at": row["created_at"],
                    }
                )
        return effective

    @staticmethod
    def _snapshot(
        requirement: dict[str, Any],
        evidence: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        candidates = [
            item
            for item in evidence
            if item["subject_type"] == requirement["subject_type"]
            and item["subject_id"] == requirement["subject_id"]
        ]
        by_evaluation: dict[str, list[dict[str, Any]]] = {}
        for item in candidates:
            by_evaluation.setdefault(str(item["evaluation_id"]), []).append(item)
        attempts: list[dict[str, Any]] = []
        for values in by_evaluation.values():
            representative = dict(values[0])
            levels = [
                (float(item["level"]), float(item["confidence"])) for item in values
            ]
            representative["level"] = _weighted_median(levels)
            representative["confidence"] = sum(
                float(item["confidence"]) for item in values
            ) / len(values)
            attempts.append(representative)
        latest_by_question: dict[str, dict[str, Any]] = {}
        for item in attempts:
            question_id = str(item["question_id"])
            existing = latest_by_question.get(question_id)
            if existing is None or str(item["created_at"]) > str(existing["created_at"]):
                latest_by_question[question_id] = item
        current = list(latest_by_question.values())
        weighted: list[tuple[float, float]] = []
        for item in current:
            age_days = max(0, (now - _parse_timestamp(str(item["created_at"]))).days)
            if age_days <= 30:
                recency = 1.0
            elif age_days <= 90:
                recency = 0.75
            elif age_days <= 180:
                recency = 0.5
            else:
                recency = 0.25
            weighted.append(
                (float(item["level"]), float(item["confidence"]) * recency)
            )
        level = _weighted_median(weighted)
        required_count = max(3, int(requirement["minimum_evidence_count"]))
        recent_attempts = sum(
            max(0, (now - _parse_timestamp(str(item["created_at"]))).days) <= 30
            for item in attempts
        )
        distinct_questions = len({str(item["question_id"]) for item in attempts})
        coverage_met = (
            len(attempts) >= required_count
            and distinct_questions >= 2
            and recent_attempts >= 1
        )
        if not attempts:
            status = "no_evidence"
        elif recent_attempts == 0:
            status = "needs_revalidation"
        elif not coverage_met:
            status = "insufficient"
        elif level is not None and level < int(requirement["required_level"]):
            status = "below"
        else:
            status = "meets"
        return {
            "subject_type": requirement["subject_type"],
            "subject_id": requirement["subject_id"],
            "subject_name": requirement["subject_name"],
            "required_level": requirement["required_level"],
            "current_level": level,
            "critical": bool(requirement["critical"]),
            "weight": requirement["weight"],
            "status": status,
            "coverage": {
                "eligible_attempts": len(attempts),
                "required_attempts": required_count,
                "distinct_questions": distinct_questions,
                "required_distinct_questions": 2,
                "recent_attempts_30d": recent_attempts,
                "required_recent_attempts_30d": 1,
            },
            "latest_evidence_at": (
                max(str(item["created_at"]) for item in current) if current else None
            ),
        }

    @staticmethod
    def _next_action(snapshot: dict[str, Any]) -> str:
        status = snapshot["status"]
        if status == "no_evidence":
            return "Complete an independent interview answer for this requirement."
        if status == "needs_revalidation":
            return "Schedule a different-question reassessment within 30 days."
        if status == "insufficient":
            coverage = snapshot["coverage"]
            return (
                "Collect independent evidence until coverage reaches "
                f"{coverage['required_attempts']} attempts across at least 2 questions."
            )
        return "Practice the recorded gaps, then retest with a different question."

    @staticmethod
    def _render_markdown(dashboard: dict[str, Any]) -> str:
        summary = cast(dict[str, Any], dashboard["summary"])
        requirements = cast(list[dict[str, Any]], dashboard["requirements"])
        lines = [
            "# Interview readiness",
            "",
            f"- Readiness: **{dashboard['readiness']}**",
            f"- Critical blockers: {summary['critical_blockers']}",
            f"- Evidence gaps: {summary['evidence_gaps']}",
            f"- Unresolved disputes: {summary['unresolved_disputes']}",
            "",
            "| Requirement | Target | Current | Status | Evidence coverage |",
            "|---|---:|---:|---|---|",
        ]
        for item in requirements:
            coverage = cast(dict[str, Any], item["coverage"])
            current = "N/A" if item["current_level"] is None else item["current_level"]
            critical = " (critical)" if item["critical"] else ""
            lines.append(
                f"| {item['subject_name']}{critical} | {item['required_level']} | "
                f"{current} | {item['status']} | {coverage['eligible_attempts']}/"
                f"{coverage['required_attempts']} attempts; "
                f"{coverage['distinct_questions']}/2 questions |"
            )
        return "\n".join(lines)
