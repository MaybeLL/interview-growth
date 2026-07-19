"""Capture real interview memories without promoting them to formal evidence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.application.question_bank import QuestionBankService
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import RealInterviewQuestionInput
from interview_growth.domain.validation import new_id, request_hash, require_text
from interview_growth.persistence.real_interview_repository import RealInterviewRepository

_RESULTS = {"passed", "rejected", "pending", "unknown"}


class RealInterviewService:
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

    def record(
        self,
        *,
        session_id: str,
        company: str,
        role_title: str,
        round_name: str,
        interviewed_at: str,
        result: str,
        overall_notes: str,
        questions: Sequence[RealInterviewQuestionInput],
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_company = require_text(company, field="Company", maximum=300)
        clean_role = require_text(role_title, field="Role title", maximum=300)
        clean_round = require_text(round_name, field="Interview round", maximum=300)
        clean_interviewed_at = require_text(
            interviewed_at, field="Interview time", maximum=100
        )
        clean_notes = " ".join(overall_notes.split())
        if len(clean_notes) > 20_000:
            raise DomainValidationError("Overall notes must be at most 20000 characters.")
        if result not in _RESULTS:
            raise DomainValidationError(
                "Real interview result must be passed, rejected, pending, or unknown."
            )
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=160)
        if not questions:
            raise DomainValidationError(
                "A real interview review needs at least one recalled question."
            )
        question_bank = QuestionBankService(
            self._goals, clock=self._clock, id_factory=self._id_factory
        )
        memories: list[dict[str, Any]] = []
        for index, item in enumerate(questions, start=1):
            if not 0 <= item.recall_confidence <= 1:
                raise DomainValidationError("Recall confidence must be between 0 and 1.")
            prompt = require_text(item.prompt, field="Recalled question", maximum=20_000)
            answer = " ".join(item.answer_summary.split())
            feedback = " ".join(item.interviewer_feedback.split())
            if len(answer) > 100_000 or len(feedback) > 20_000:
                raise DomainValidationError("Real interview memory text is too long.")
            captured = question_bank.capture(
                session_id=session_id,
                prompt=prompt,
                source=f"real-interview:{clean_company}:{clean_round}"[:200],
                topic_ids=item.topic_ids,
                capability_ids=item.capability_ids,
                idempotency_key=f"{clean_key}:q:{index}",
            )
            memories.append(
                {
                    "id": self._id_factory(),
                    "prompt": prompt,
                    "answer_summary": answer,
                    "interviewer_feedback": feedback,
                    "question_id": captured.id,
                    "topic_ids": list(item.topic_ids),
                    "capability_ids": list(item.capability_ids),
                    "recall_confidence": item.recall_confidence,
                }
            )
        timestamp = self._clock()
        hash_memories = [
            {key: value for key, value in memory.items() if key != "id"}
            for memory in memories
        ]
        return self._repository(session_id).create(
            review_id=self._id_factory(),
            company=clean_company,
            role_title=clean_role,
            round_name=clean_round,
            interviewed_at=clean_interviewed_at,
            result=result,
            overall_notes=clean_notes,
            memories=memories,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "company": clean_company,
                    "role_title": clean_role,
                    "round_name": clean_round,
                    "interviewed_at": clean_interviewed_at,
                    "result": result,
                    "overall_notes": clean_notes,
                    "questions": hash_memories,
                }
            ),
        )

    def get(self, *, session_id: str, review_id: str) -> dict[str, Any]:
        return self._repository(session_id).get(review_id)

    def list(self, *, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("Review list limit must be between 1 and 100.")
        return self._repository(session_id).list(limit)

    def _repository(self, session_id: str) -> RealInterviewRepository:
        goal, path = self._goals.resolve_current_goal_database(session_id=session_id)
        return RealInterviewRepository(path, goal.id)
