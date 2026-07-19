"""Mock interview orchestration, raw attempts, evaluation, and coached practice."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import (
    AssistanceLevel,
    Attempt,
    DimensionEvaluationInput,
    Evaluation,
    InterviewItem,
    InterviewItemKind,
    InterviewItemStatus,
    InterviewSession,
    InterviewStatus,
    PracticeRecord,
    QuestionStatus,
)
from interview_growth.domain.validation import new_id, request_hash, require_text
from interview_growth.persistence.interview_repository import InterviewRepository
from interview_growth.persistence.question_repository import QuestionRepository
from interview_growth.persistence.standard_repository import StandardRepository

_REQUIRED_PLAN_FIELDS = {
    "scope",
    "difficulty",
    "question_budget",
    "time_budget_minutes",
    "source_strategy",
    "feedback_timing",
}
_REQUIRED_PROVENANCE_FIELDS = {"evaluator", "host", "model", "prompt_version"}


class InterviewService:
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

    def start(
        self,
        *,
        session_id: str,
        plan: Mapping[str, object],
        question_ids: Sequence[str],
        idempotency_key: str,
    ) -> InterviewSession:
        clean_plan = dict(plan)
        self._validate_plan(clean_plan)
        clean_question_ids = tuple(dict.fromkeys(question_ids))
        if not clean_question_ids:
            raise DomainValidationError("An interview must start with at least one question.")
        question_budget = clean_plan["question_budget"]
        if not isinstance(question_budget, int):
            raise RuntimeError("Validated interview question budget is not an integer.")
        if len(clean_question_ids) > question_budget:
            raise DomainValidationError("Initial questions exceed the interview question budget.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        interview, questions, standards = self._repositories(session_id)
        standard = standards.current_version()
        if standard is None:
            raise DomainValidationError(
                "A formal interview requires an approved target standard."
            )
        interview_id = self._id_factory()
        timestamp = self._clock()
        items: list[InterviewItem] = []
        frozen_questions: list[dict[str, object]] = []
        for sequence, question_id in enumerate(clean_question_ids, start=1):
            question = questions.get(question_id)
            if question.status is not QuestionStatus.ASSESSABLE:
                raise DomainValidationError(
                    f"Question {question_id} is not currently assessable."
                )
            items.append(
                InterviewItem(
                    id=self._id_factory(),
                    interview_id=interview_id,
                    question_id=question.id,
                    question_version=question.current_version,
                    kind=InterviewItemKind.MAIN,
                    parent_item_id=None,
                    trigger_attempt_id=None,
                    sequence_number=sequence,
                    status=InterviewItemStatus.QUEUED,
                    registered_at=timestamp,
                )
            )
            frozen_questions.append(
                {"question_id": question.id, "version": question.current_version}
            )
        return interview.start(
            interview_id=interview_id,
            host_session_id=require_text(session_id, field="Session ID", maximum=200),
            standard_version_id=standard.id,
            plan=clean_plan,
            items=tuple(items),
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "plan": clean_plan,
                    "questions": frozen_questions,
                    "standard_version_id": standard.id,
                }
            ),
        )

    def get_state(self, *, session_id: str, interview_id: str) -> InterviewSession:
        interview, _, _ = self._repositories(session_id)
        return interview.get(interview_id)

    def register_question(
        self,
        *,
        session_id: str,
        interview_id: str,
        question_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> InterviewSession:
        return self._register_item(
            session_id=session_id,
            interview_id=interview_id,
            question_id=question_id,
            expected_revision=expected_revision,
            kind=InterviewItemKind.MAIN,
            parent_item_id=None,
            trigger_attempt_id=None,
            idempotency_key=idempotency_key,
        )

    def register_followup(
        self,
        *,
        session_id: str,
        interview_id: str,
        question_id: str,
        parent_item_id: str,
        trigger_attempt_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> InterviewSession:
        return self._register_item(
            session_id=session_id,
            interview_id=interview_id,
            question_id=question_id,
            expected_revision=expected_revision,
            kind=InterviewItemKind.FOLLOWUP,
            parent_item_id=parent_item_id,
            trigger_attempt_id=trigger_attempt_id,
            idempotency_key=idempotency_key,
        )

    def record_attempt(
        self,
        *,
        session_id: str,
        interview_id: str,
        interview_item_id: str,
        expected_revision: int,
        answer_text: str,
        assistance_level: AssistanceLevel,
        idempotency_key: str,
    ) -> Attempt:
        clean_answer = require_text(answer_text, field="Raw answer", maximum=100_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        interview, _, _ = self._repositories(session_id)
        state = interview.get(interview_id)
        item = next((value for value in state.items if value.id == interview_item_id), None)
        if item is None:
            raise DomainValidationError("Unknown interview question item.")
        timestamp = self._clock()
        attempt = Attempt(
            id=self._id_factory(),
            interview_id=interview_id,
            interview_item_id=item.id,
            question_id=item.question_id,
            question_version=item.question_version,
            answer_text=clean_answer,
            assistance_level=assistance_level,
            recorded_at=timestamp,
        )
        return interview.record_attempt(
            attempt=attempt,
            expected_revision=expected_revision,
            checkpoint_id=self._id_factory(),
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "interview_id": interview_id,
                    "interview_item_id": interview_item_id,
                    "expected_revision": expected_revision,
                    "answer_text": clean_answer,
                    "assistance_level": assistance_level.value,
                }
            ),
        )

    def submit_evaluation(
        self,
        *,
        session_id: str,
        interview_id: str,
        attempt_id: str,
        expected_revision: int,
        summary: str,
        dimensions: Sequence[DimensionEvaluationInput],
        evaluator_provenance: Mapping[str, object],
        idempotency_key: str,
    ) -> Evaluation:
        clean_summary = require_text(summary, field="Evaluation summary", maximum=10_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        clean_dimensions = self._validate_dimensions(dimensions)
        provenance = dict(evaluator_provenance)
        missing = _REQUIRED_PROVENANCE_FIELDS - provenance.keys()
        if missing:
            raise DomainValidationError(
                f"Evaluator provenance is missing: {', '.join(sorted(missing))}."
            )
        interview, questions, _ = self._repositories(session_id)
        state = interview.get(interview_id)
        attempt = interview.get_attempt(attempt_id)
        if attempt.interview_id != interview_id:
            raise DomainValidationError("Attempt does not belong to this interview.")
        frozen_question = questions.get_version(
            attempt.question_id, attempt.question_version
        )
        if frozen_question.rubric is None:
            raise DomainValidationError("The frozen question version has no rubric.")
        submitted_ids = {item.capability_id for item in clean_dimensions}
        if not submitted_ids <= set(frozen_question.capability_ids):
            raise DomainValidationError(
                "Evaluation includes a capability not mapped to the frozen question."
            )
        eligible = (
            attempt.assistance_level is AssistanceLevel.INDEPENDENT
            and all(item.level is not None for item in clean_dimensions)
            and all(item.confidence >= 0.5 for item in clean_dimensions)
        )
        timestamp = self._clock()
        evaluation = Evaluation(
            id=self._id_factory(),
            attempt_id=attempt.id,
            interview_id=interview_id,
            standard_version_id=state.standard_version_id,
            question_id=attempt.question_id,
            question_version=attempt.question_version,
            summary=clean_summary,
            evaluator_provenance=provenance,
            evidence_eligible=eligible,
            created_at=timestamp,
            dimensions=(),
        )
        return interview.submit_evaluation(
            evaluation=evaluation,
            dimension_inputs=clean_dimensions,
            expected_revision=expected_revision,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "interview_id": interview_id,
                    "attempt_id": attempt_id,
                    "expected_revision": expected_revision,
                    "summary": clean_summary,
                    "dimensions": [self._dimension_payload(item) for item in clean_dimensions],
                    "evaluator_provenance": provenance,
                }
            ),
        )

    def checkpoint(
        self,
        *,
        session_id: str,
        interview_id: str,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> InterviewSession:
        clean_reason = require_text(reason, field="Checkpoint reason", maximum=200)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        interview, _, _ = self._repositories(session_id)
        return interview.checkpoint(
            interview_id=interview_id,
            checkpoint_id=self._id_factory(),
            expected_revision=expected_revision,
            reason=clean_reason,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "interview_id": interview_id,
                    "expected_revision": expected_revision,
                    "reason": clean_reason,
                }
            ),
        )

    def pause(
        self,
        *,
        session_id: str,
        interview_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> InterviewSession:
        return self._transition(
            session_id=session_id,
            interview_id=interview_id,
            expected_revision=expected_revision,
            requested=InterviewStatus.PAUSED,
            outcome_summary=None,
            idempotency_key=idempotency_key,
        )

    def resume(
        self,
        *,
        session_id: str,
        interview_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> InterviewSession:
        return self._transition(
            session_id=session_id,
            interview_id=interview_id,
            expected_revision=expected_revision,
            requested=InterviewStatus.IN_PROGRESS,
            outcome_summary=None,
            idempotency_key=idempotency_key,
        )

    def finish(
        self,
        *,
        session_id: str,
        interview_id: str,
        expected_revision: int,
        outcome_summary: str,
        aborted: bool,
        idempotency_key: str,
    ) -> InterviewSession:
        clean_summary = require_text(
            outcome_summary, field="Interview outcome summary", maximum=20_000
        )
        return self._transition(
            session_id=session_id,
            interview_id=interview_id,
            expected_revision=expected_revision,
            requested=InterviewStatus.ABORTED if aborted else InterviewStatus.COMPLETED,
            outcome_summary=clean_summary,
            idempotency_key=idempotency_key,
        )

    def record_practice(
        self,
        *,
        session_id: str,
        question_id: str,
        response_text: str,
        assistance_level: AssistanceLevel,
        coach_notes: str,
        idempotency_key: str,
    ) -> PracticeRecord:
        if assistance_level is AssistanceLevel.INDEPENDENT:
            raise DomainValidationError(
                "Coach practice must be marked hinted or coached, never independent."
            )
        clean_response = require_text(
            response_text, field="Practice response", maximum=100_000
        )
        clean_notes = require_text(coach_notes, field="Coach notes", maximum=20_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        interview, questions, _ = self._repositories(session_id)
        question = questions.get(question_id)
        timestamp = self._clock()
        record = PracticeRecord(
            id=self._id_factory(),
            question_id=question.id,
            question_version=question.current_version,
            response_text=clean_response,
            assistance_level=assistance_level,
            coach_notes=clean_notes,
            created_at=timestamp,
        )
        return interview.record_practice(
            record=record,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "question_id": question.id,
                    "question_version": question.current_version,
                    "response_text": clean_response,
                    "assistance_level": assistance_level.value,
                    "coach_notes": clean_notes,
                }
            ),
        )

    def evaluator_context(
        self,
        *,
        session_id: str,
        interview_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        interview, questions, standards = self._repositories(session_id)
        state = interview.get(interview_id)
        attempt = interview.get_attempt(attempt_id)
        if attempt.interview_id != interview_id:
            raise DomainValidationError("Attempt does not belong to this interview.")
        question = questions.get_version(attempt.question_id, attempt.question_version)
        standard = standards.get_version(state.standard_version_id)
        return {
            "interview_id": interview_id,
            "interview_revision": state.revision,
            "standard": {
                "id": standard.id,
                "version_number": standard.version_number,
                "role_profile": standard.role_profile,
                "capability_requirements": [
                    {
                        "capability_id": item.subject_id,
                        "name": item.subject_name,
                        "required_level": item.required_level,
                    }
                    for item in standard.capability_requirements
                ],
            },
            "frozen_question": {
                "question_id": question.question_id,
                "version": question.version,
                "prompt": question.prompt,
                "intent": question.intent,
                "rubric": question.rubric,
                "capability_ids": list(question.capability_ids),
            },
            "attempt": {
                "id": attempt.id,
                "answer_text": attempt.answer_text,
                "assistance_level": attempt.assistance_level.value,
            },
        }

    def interviewer_context(
        self,
        *,
        session_id: str,
        interview_id: str,
    ) -> dict[str, object]:
        interview, questions, _ = self._repositories(session_id)
        state = interview.get(interview_id)
        current = next(
            (item for item in state.items if item.status is InterviewItemStatus.QUEUED),
            None,
        )
        current_payload: dict[str, object] | None = None
        if current is not None:
            question = questions.get_version(current.question_id, current.question_version)
            followups: object = []
            if question.rubric is not None:
                followups = question.rubric.get("follow_up_directions", [])
            current_payload = {
                "item_id": current.id,
                "kind": current.kind.value,
                "question_id": current.question_id,
                "question_version": current.question_version,
                "prompt": question.prompt,
                "follow_up_directions": followups,
            }
        return {
            "interview_id": state.id,
            "status": state.status.value,
            "revision": state.revision,
            "plan": state.plan,
            "current_question": current_payload,
            "progress": {
                status.value: sum(item.status is status for item in state.items)
                for status in InterviewItemStatus
            },
        }

    def coach_context(
        self,
        *,
        session_id: str,
        interview_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        context = self.evaluator_context(
            session_id=session_id,
            interview_id=interview_id,
            attempt_id=attempt_id,
        )
        interview, _, _ = self._repositories(session_id)
        evaluation = interview.find_evaluation_for_attempt(attempt_id)
        context["evaluation"] = (
            None
            if evaluation is None
            else {
                "id": evaluation.id,
                "summary": evaluation.summary,
                "evidence_eligible": evaluation.evidence_eligible,
                "dimensions": [
                    {
                        "capability_id": item.capability_id,
                        "capability_name": item.capability_name,
                        "level": item.level,
                        "evidence": item.evidence,
                        "gaps": item.gaps,
                        "improvement": item.improvement,
                        "confidence": item.confidence,
                    }
                    for item in evaluation.dimensions
                ],
            }
        )
        context["evidence_rule"] = (
            "Any answer produced with hints or coaching must be stored as assisted practice."
        )
        return context

    def find_active(self, *, session_id: str) -> InterviewSession | None:
        interview, _, _ = self._repositories(session_id)
        return interview.find_active()

    def _register_item(
        self,
        *,
        session_id: str,
        interview_id: str,
        question_id: str,
        expected_revision: int,
        kind: InterviewItemKind,
        parent_item_id: str | None,
        trigger_attempt_id: str | None,
        idempotency_key: str,
    ) -> InterviewSession:
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        interview, questions, _ = self._repositories(session_id)
        state = interview.get(interview_id)
        question_budget = state.plan.get("question_budget")
        if not isinstance(question_budget, int):
            raise RuntimeError("Stored interview plan has an invalid question budget.")
        if len(state.items) >= question_budget:
            raise DomainValidationError("Interview question budget has been reached.")
        question = questions.get(question_id)
        if question.status is not QuestionStatus.ASSESSABLE:
            raise DomainValidationError("Only an assessable question can enter an interview.")
        timestamp = self._clock()
        item = InterviewItem(
            id=self._id_factory(),
            interview_id=interview_id,
            question_id=question.id,
            question_version=question.current_version,
            kind=kind,
            parent_item_id=parent_item_id,
            trigger_attempt_id=trigger_attempt_id,
            sequence_number=len(state.items) + 1,
            status=InterviewItemStatus.QUEUED,
            registered_at=timestamp,
        )
        return interview.register_item(
            item=item,
            expected_revision=expected_revision,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "interview_id": interview_id,
                    "question_id": question.id,
                    "question_version": question.current_version,
                    "expected_revision": expected_revision,
                    "kind": kind.value,
                    "parent_item_id": parent_item_id,
                    "trigger_attempt_id": trigger_attempt_id,
                }
            ),
        )

    def _transition(
        self,
        *,
        session_id: str,
        interview_id: str,
        expected_revision: int,
        requested: InterviewStatus,
        outcome_summary: str | None,
        idempotency_key: str,
    ) -> InterviewSession:
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        interview, _, _ = self._repositories(session_id)
        return interview.transition(
            interview_id=interview_id,
            expected_revision=expected_revision,
            requested=requested,
            timestamp=timestamp,
            outcome_summary=outcome_summary,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "interview_id": interview_id,
                    "expected_revision": expected_revision,
                    "requested": requested.value,
                    "outcome_summary": outcome_summary,
                }
            ),
        )

    def _repositories(
        self, session_id: str
    ) -> tuple[InterviewRepository, QuestionRepository, StandardRepository]:
        goal, path = self._goals.resolve_current_goal_database(session_id=session_id)
        return (
            InterviewRepository(path, goal.id),
            QuestionRepository(path, goal.id),
            StandardRepository(path, goal.id),
        )

    @staticmethod
    def _validate_plan(plan: dict[str, object]) -> None:
        missing = _REQUIRED_PLAN_FIELDS - plan.keys()
        if missing:
            raise DomainValidationError(
                f"Interview plan is missing: {', '.join(sorted(missing))}."
            )
        question_budget = plan["question_budget"]
        time_budget = plan["time_budget_minutes"]
        if not isinstance(question_budget, int) or not 1 <= question_budget <= 100:
            raise DomainValidationError("Question budget must be between 1 and 100.")
        if not isinstance(time_budget, int) or not 5 <= time_budget <= 480:
            raise DomainValidationError("Time budget must be between 5 and 480 minutes.")
        for field in ("scope", "difficulty", "source_strategy", "feedback_timing"):
            value = plan[field]
            if not isinstance(value, str) or not value.strip():
                raise DomainValidationError(f"Interview plan field {field} must be text.")

    @staticmethod
    def _validate_dimensions(
        dimensions: Sequence[DimensionEvaluationInput],
    ) -> tuple[DimensionEvaluationInput, ...]:
        if not dimensions:
            raise DomainValidationError("At least one dimension evaluation is required.")
        seen: set[str] = set()
        result: list[DimensionEvaluationInput] = []
        for item in dimensions:
            if item.capability_id in seen:
                raise DomainValidationError(
                    f"Duplicate capability evaluation: {item.capability_id}"
                )
            seen.add(item.capability_id)
            if item.level is not None and not 0 <= item.level <= 4:
                raise DomainValidationError("Evaluation level must be 0-4 or N/A.")
            if not 0 <= item.confidence <= 1:
                raise DomainValidationError("Evaluation confidence must be between 0 and 1.")
            evidence = " ".join(item.evidence.split())
            gaps = " ".join(item.gaps.split())
            improvement = " ".join(item.improvement.split())
            if item.level is None and evidence:
                raise DomainValidationError("N/A dimension evaluations must not claim evidence.")
            if item.level is not None and not evidence:
                raise DomainValidationError("A scored dimension requires answer evidence.")
            if not improvement:
                raise DomainValidationError("Every dimension evaluation needs improvement advice.")
            result.append(
                DimensionEvaluationInput(
                    capability_id=item.capability_id,
                    level=item.level,
                    evidence=evidence,
                    gaps=gaps,
                    improvement=improvement,
                    confidence=item.confidence,
                )
            )
        return tuple(result)

    @staticmethod
    def _dimension_payload(item: DimensionEvaluationInput) -> dict[str, object]:
        return {
            "capability_id": item.capability_id,
            "level": item.level,
            "evidence": item.evidence,
            "gaps": item.gaps,
            "improvement": item.improvement,
            "confidence": item.confidence,
        }
