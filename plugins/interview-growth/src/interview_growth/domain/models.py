"""Core domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import InvalidLifecycleTransitionError


class GoalLifecycle(StrEnum):
    """User-controlled lifecycle for a growth goal."""

    CONFIGURING = "configuring"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    ENDED = "ended"
    ARCHIVED = "archived"


class ContextRole(StrEnum):
    """Roles that may receive a minimal Context Packet."""

    GOAL_MANAGER = "goal_manager"
    INTERVIEWER = "interviewer"
    EVALUATOR = "evaluator"
    COACH = "coach"


class SourceMaterialKind(StrEnum):
    JOB_DESCRIPTION = "job_description"
    USER_CONSTRAINT = "user_constraint"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ASSESSABLE = "assessable"
    RETIRED = "retired"


class InterviewStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class InterviewItemKind(StrEnum):
    MAIN = "main"
    FOLLOWUP = "followup"


class InterviewItemStatus(StrEnum):
    QUEUED = "queued"
    ANSWERED = "answered"
    EVALUATED = "evaluated"
    SKIPPED = "skipped"


class AssistanceLevel(StrEnum):
    INDEPENDENT = "independent"
    HINTED = "hinted"
    COACHED = "coached"


_ALLOWED_TRANSITIONS: dict[GoalLifecycle, frozenset[GoalLifecycle]] = {
    GoalLifecycle.CONFIGURING: frozenset({GoalLifecycle.IN_PROGRESS}),
    GoalLifecycle.IN_PROGRESS: frozenset({GoalLifecycle.PAUSED, GoalLifecycle.ENDED}),
    GoalLifecycle.PAUSED: frozenset({GoalLifecycle.IN_PROGRESS, GoalLifecycle.ENDED}),
    GoalLifecycle.ENDED: frozenset({GoalLifecycle.ARCHIVED}),
    GoalLifecycle.ARCHIVED: frozenset(),
}


def require_lifecycle_transition(
    current: GoalLifecycle,
    requested: GoalLifecycle,
) -> None:
    """Validate a lifecycle transition, treating a repeated request as idempotent."""

    if current == requested:
        return
    if requested not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(
            f"Cannot transition a goal from {current.value!r} to {requested.value!r}."
        )


@dataclass(frozen=True, slots=True)
class Goal:
    """Registry-level summary for a physically isolated growth goal."""

    id: str
    slug: str
    name: str
    lifecycle: GoalLifecycle
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceMaterial:
    id: str
    kind: SourceMaterialKind
    title: str
    content: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    canonical_name: str
    description: str
    parent_id: str | None
    aliases: tuple[str, ...]
    status: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CapabilityDimension:
    id: str
    canonical_name: str
    description: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Requirement:
    subject_id: str
    subject_name: str
    required_level: int
    weight: float
    critical: bool
    minimum_evidence_count: int


@dataclass(frozen=True, slots=True)
class RequirementInput:
    subject_id: str
    required_level: int
    weight: float
    critical: bool
    minimum_evidence_count: int


@dataclass(frozen=True, slots=True)
class StandardDraft:
    id: str
    revision: int
    status: str
    role_profile: dict[str, object]
    source_ids: tuple[str, ...]
    topic_requirements: tuple[Requirement, ...]
    capability_requirements: tuple[Requirement, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StandardVersion:
    id: str
    version_number: int
    source_draft_id: str
    source_draft_revision: int
    role_profile: dict[str, object]
    source_ids: tuple[str, ...]
    topic_requirements: tuple[Requirement, ...]
    capability_requirements: tuple[Requirement, ...]
    approved_at: str


@dataclass(frozen=True, slots=True)
class QuestionVersion:
    question_id: str
    version: int
    prompt: str
    intent: str | None
    rubric: dict[str, object] | None
    topic_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    created_at: str


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    status: QuestionStatus
    source: str
    current_version: int
    created_at: str
    updated_at: str
    retired_at: str | None
    version: QuestionVersion


@dataclass(frozen=True, slots=True)
class InterviewItem:
    id: str
    interview_id: str
    question_id: str
    question_version: int
    kind: InterviewItemKind
    parent_item_id: str | None
    trigger_attempt_id: str | None
    sequence_number: int
    status: InterviewItemStatus
    registered_at: str


@dataclass(frozen=True, slots=True)
class InterviewSession:
    id: str
    status: InterviewStatus
    standard_version_id: str
    plan: dict[str, object]
    revision: int
    started_at: str
    updated_at: str
    paused_at: str | None
    completed_at: str | None
    outcome_summary: str | None
    items: tuple[InterviewItem, ...]


@dataclass(frozen=True, slots=True)
class Attempt:
    id: str
    interview_id: str
    interview_item_id: str
    question_id: str
    question_version: int
    answer_text: str
    assistance_level: AssistanceLevel
    recorded_at: str


@dataclass(frozen=True, slots=True)
class DimensionEvaluationInput:
    capability_id: str
    level: int | None
    evidence: str
    gaps: str
    improvement: str
    confidence: float


@dataclass(frozen=True, slots=True)
class DimensionEvaluation:
    capability_id: str
    capability_name: str
    level: int | None
    evidence: str
    gaps: str
    improvement: str
    confidence: float


@dataclass(frozen=True, slots=True)
class Evaluation:
    id: str
    attempt_id: str
    interview_id: str
    standard_version_id: str
    question_id: str
    question_version: int
    summary: str
    evaluator_provenance: dict[str, object]
    evidence_eligible: bool
    created_at: str
    dimensions: tuple[DimensionEvaluation, ...]


@dataclass(frozen=True, slots=True)
class PracticeRecord:
    id: str
    question_id: str
    question_version: int
    response_text: str
    assistance_level: AssistanceLevel
    coach_notes: str
    created_at: str


@dataclass(frozen=True, slots=True)
class RealInterviewQuestionInput:
    prompt: str
    answer_summary: str
    interviewer_feedback: str
    topic_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    recall_confidence: float
