"""Build minimal, role-scoped context from deterministic registry state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from interview_growth.domain.models import ContextRole

from .goals import GoalService, utc_now
from .interviews import InterviewService
from .question_bank import QuestionBankService
from .standards import StandardService


@dataclass(frozen=True, slots=True)
class ContextPacket:
    packet_version: int
    role: ContextRole
    task: str
    generated_at: str
    goal_binding: dict[str, str]
    payload: dict[str, Any]
    provenance: dict[str, Any]
    budget: dict[str, int]


class ContextService:
    """Create a Packet without exposing paths or unrelated goal data."""

    def __init__(self, goals: GoalService) -> None:
        self._goals = goals

    def build(
        self,
        *,
        session_id: str,
        role: ContextRole,
        task: str,
        max_tokens: int = 1200,
        interview_id: str | None = None,
        attempt_id: str | None = None,
    ) -> ContextPacket:
        if max_tokens < 256 or max_tokens > 8000:
            raise ValueError("Context token budget must be between 256 and 8000.")
        goal = self._goals.get_current_goal(session_id=session_id)
        standard = StandardService(self._goals).current_version(session_id=session_id)
        question_counts = QuestionBankService(self._goals).counts(session_id=session_id)
        payload: dict[str, Any] = {
            "m1_status": "standard_approved" if standard is not None else "standard_not_approved",
            "allowed_actions": self._allowed_actions(role),
        }
        if standard is not None:
            payload["target_standard"] = {
                "version_id": standard.id,
                "version_number": standard.version_number,
                "role_profile": standard.role_profile,
                "topic_requirements": [
                    {
                        "topic_id": item.subject_id,
                        "name": item.subject_name,
                        "required_level": item.required_level,
                        "critical": item.critical,
                    }
                    for item in standard.topic_requirements
                ],
                "capability_requirements": [
                    {
                        "capability_id": item.subject_id,
                        "name": item.subject_name,
                        "required_level": item.required_level,
                        "critical": item.critical,
                    }
                    for item in standard.capability_requirements
                ],
            }
        if role in {ContextRole.GOAL_MANAGER, ContextRole.INTERVIEWER, ContextRole.COACH}:
            payload["question_counts"] = question_counts
        if interview_id is not None:
            interviews = InterviewService(self._goals)
            if role is ContextRole.INTERVIEWER:
                payload["interview"] = interviews.interviewer_context(
                    session_id=session_id,
                    interview_id=interview_id,
                )
            elif role is ContextRole.EVALUATOR:
                if attempt_id is None:
                    raise ValueError("Evaluator context requires an attempt ID.")
                payload["evaluation_context"] = interviews.evaluator_context(
                    session_id=session_id,
                    interview_id=interview_id,
                    attempt_id=attempt_id,
                )
            elif role is ContextRole.COACH:
                if attempt_id is None:
                    raise ValueError("Coach context requires an attempt ID.")
                payload["coach_context"] = interviews.coach_context(
                    session_id=session_id,
                    interview_id=interview_id,
                    attempt_id=attempt_id,
                )
        return ContextPacket(
            packet_version=3,
            role=role,
            task=task,
            generated_at=utc_now(),
            goal_binding={
                "goal_id": goal.id,
                "goal_name": goal.name,
                "lifecycle": goal.lifecycle.value,
            },
            payload=payload,
            provenance={
                "registry_schema_version": 1,
                "goal_schema_version": 3,
                "source_goal_ids": [goal.id],
            },
            budget={"max_tokens": max_tokens},
        )

    @staticmethod
    def _allowed_actions(role: ContextRole) -> list[str]:
        if role is ContextRole.GOAL_MANAGER:
            return [
                "read_goal_summary",
                "change_goal_lifecycle",
                "manage_target_standard",
                "manage_taxonomy",
            ]
        if role is ContextRole.INTERVIEWER:
            return ["read_target_requirements", "search_assessable_questions"]
        if role is ContextRole.EVALUATOR:
            return ["read_target_requirements", "read_frozen_question_rubric"]
        if role is ContextRole.COACH:
            return ["read_target_requirements", "search_practice_questions"]
        return ["read_goal_binding"]
