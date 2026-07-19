"""Pydantic contracts shared by MCP and CLI adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from interview_growth.application.context import ContextPacket
from interview_growth.application.goals import DoctorReport
from interview_growth.application.question_bank import QuestionDuplicateSuggestion
from interview_growth.application.standards import DuplicateSuggestion
from interview_growth.domain.models import (
    Attempt,
    CapabilityDimension,
    DimensionEvaluation,
    DimensionEvaluationInput,
    Evaluation,
    Goal,
    InterviewItem,
    InterviewSession,
    PracticeRecord,
    Question,
    QuestionVersion,
    RealInterviewQuestionInput,
    Requirement,
    RequirementInput,
    SourceMaterial,
    StandardDraft,
    StandardVersion,
    Topic,
)


class GoalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    slug: str
    name: str
    lifecycle: str
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, goal: Goal) -> GoalOutput:
        return cls(
            id=goal.id,
            slug=goal.slug,
            name=goal.name,
            lifecycle=goal.lifecycle.value,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )


class GoalListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goals: tuple[GoalOutput, ...]


class ContextPacketOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    packet_version: int
    role: str
    task: str
    generated_at: str
    goal_binding: dict[str, str]
    payload: dict[str, Any]
    provenance: dict[str, Any]
    budget: dict[str, int]

    @classmethod
    def from_domain(cls, packet: ContextPacket) -> ContextPacketOutput:
        return cls(
            packet_version=packet.packet_version,
            role=packet.role.value,
            task=packet.task,
            generated_at=packet.generated_at,
            goal_binding=packet.goal_binding,
            payload=packet.payload,
            provenance=packet.provenance,
            budget=packet.budget,
        )


class DoctorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    goals_checked: int
    issues: tuple[str, ...]

    @classmethod
    def from_domain(cls, report: DoctorReport) -> DoctorOutput:
        return cls(
            ok=report.ok,
            goals_checked=report.goals_checked,
            issues=report.issues,
        )


class RequirementInputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    required_level: int
    weight: float = 1.0
    critical: bool = False
    minimum_evidence_count: int = 2

    def to_domain(self) -> RequirementInput:
        return RequirementInput(**self.model_dump())


class RequirementOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    subject_name: str
    required_level: int
    weight: float
    critical: bool
    minimum_evidence_count: int

    @classmethod
    def from_domain(cls, value: Requirement) -> RequirementOutput:
        return cls(
            subject_id=value.subject_id,
            subject_name=value.subject_name,
            required_level=value.required_level,
            weight=value.weight,
            critical=value.critical,
            minimum_evidence_count=value.minimum_evidence_count,
        )


class SourceMaterialOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str
    title: str
    content: str
    created_at: str

    @classmethod
    def from_domain(cls, value: SourceMaterial) -> SourceMaterialOutput:
        return cls(
            id=value.id,
            kind=value.kind.value,
            title=value.title,
            content=value.content,
            created_at=value.created_at,
        )


class TopicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    canonical_name: str
    description: str
    parent_id: str | None
    aliases: tuple[str, ...]
    status: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, value: Topic) -> TopicOutput:
        return cls(
            id=value.id,
            canonical_name=value.canonical_name,
            description=value.description,
            parent_id=value.parent_id,
            aliases=value.aliases,
            status=value.status,
            version=value.version,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class TopicListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topics: tuple[TopicOutput, ...]


class DuplicateSuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    canonical_name: str
    score: float
    matched_by: str

    @classmethod
    def from_domain(cls, value: DuplicateSuggestion) -> DuplicateSuggestionOutput:
        return cls(
            id=value.id,
            canonical_name=value.canonical_name,
            score=value.score,
            matched_by=value.matched_by,
        )


class CapabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    canonical_name: str
    description: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, value: CapabilityDimension) -> CapabilityOutput:
        return cls(
            id=value.id,
            canonical_name=value.canonical_name,
            description=value.description,
            version=value.version,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class CapabilityListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: tuple[CapabilityOutput, ...]


class StandardDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    revision: int
    status: str
    role_profile: dict[str, Any]
    source_ids: tuple[str, ...]
    topic_requirements: tuple[RequirementOutput, ...]
    capability_requirements: tuple[RequirementOutput, ...]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, value: StandardDraft) -> StandardDraftOutput:
        return cls(
            id=value.id,
            revision=value.revision,
            status=value.status,
            role_profile=value.role_profile,
            source_ids=value.source_ids,
            topic_requirements=tuple(
                RequirementOutput.from_domain(item) for item in value.topic_requirements
            ),
            capability_requirements=tuple(
                RequirementOutput.from_domain(item) for item in value.capability_requirements
            ),
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class StandardVersionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version_number: int
    source_draft_id: str
    source_draft_revision: int
    role_profile: dict[str, Any]
    source_ids: tuple[str, ...]
    topic_requirements: tuple[RequirementOutput, ...]
    capability_requirements: tuple[RequirementOutput, ...]
    approved_at: str

    @classmethod
    def from_domain(cls, value: StandardVersion) -> StandardVersionOutput:
        return cls(
            id=value.id,
            version_number=value.version_number,
            source_draft_id=value.source_draft_id,
            source_draft_revision=value.source_draft_revision,
            role_profile=value.role_profile,
            source_ids=value.source_ids,
            topic_requirements=tuple(
                RequirementOutput.from_domain(item) for item in value.topic_requirements
            ),
            capability_requirements=tuple(
                RequirementOutput.from_domain(item) for item in value.capability_requirements
            ),
            approved_at=value.approved_at,
        )


class StandardVersionListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    versions: tuple[StandardVersionOutput, ...]


class QuestionVersionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    version: int
    prompt: str
    intent: str | None
    rubric: dict[str, Any] | None
    topic_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    created_at: str

    @classmethod
    def from_domain(cls, value: QuestionVersion) -> QuestionVersionOutput:
        return cls(
            question_id=value.question_id,
            version=value.version,
            prompt=value.prompt,
            intent=value.intent,
            rubric=value.rubric,
            topic_ids=value.topic_ids,
            capability_ids=value.capability_ids,
            created_at=value.created_at,
        )


class QuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: str
    source: str
    current_version: int
    created_at: str
    updated_at: str
    retired_at: str | None
    version: QuestionVersionOutput

    @classmethod
    def from_domain(cls, value: Question) -> QuestionOutput:
        return cls(
            id=value.id,
            status=value.status.value,
            source=value.source,
            current_version=value.current_version,
            created_at=value.created_at,
            updated_at=value.updated_at,
            retired_at=value.retired_at,
            version=QuestionVersionOutput.from_domain(value.version),
        )


class QuestionListOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: tuple[QuestionOutput, ...]


class QuestionHistoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    versions: tuple[QuestionVersionOutput, ...]


class QuestionDuplicateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    prompt: str
    score: float

    @classmethod
    def from_domain(cls, value: QuestionDuplicateSuggestion) -> QuestionDuplicateOutput:
        return cls(
            question_id=value.question_id,
            prompt=value.prompt,
            score=value.score,
        )


class InterviewItemOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    interview_id: str
    question_id: str
    question_version: int
    kind: str
    parent_item_id: str | None
    trigger_attempt_id: str | None
    sequence_number: int
    status: str
    registered_at: str

    @classmethod
    def from_domain(cls, value: InterviewItem) -> InterviewItemOutput:
        return cls(
            id=value.id,
            interview_id=value.interview_id,
            question_id=value.question_id,
            question_version=value.question_version,
            kind=value.kind.value,
            parent_item_id=value.parent_item_id,
            trigger_attempt_id=value.trigger_attempt_id,
            sequence_number=value.sequence_number,
            status=value.status.value,
            registered_at=value.registered_at,
        )


class InterviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: str
    standard_version_id: str
    plan: dict[str, Any]
    revision: int
    started_at: str
    updated_at: str
    paused_at: str | None
    completed_at: str | None
    outcome_summary: str | None
    items: tuple[InterviewItemOutput, ...]

    @classmethod
    def from_domain(cls, value: InterviewSession) -> InterviewOutput:
        return cls(
            id=value.id,
            status=value.status.value,
            standard_version_id=value.standard_version_id,
            plan=value.plan,
            revision=value.revision,
            started_at=value.started_at,
            updated_at=value.updated_at,
            paused_at=value.paused_at,
            completed_at=value.completed_at,
            outcome_summary=value.outcome_summary,
            items=tuple(InterviewItemOutput.from_domain(item) for item in value.items),
        )


class AttemptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    interview_id: str
    interview_item_id: str
    question_id: str
    question_version: int
    answer_text: str
    assistance_level: str
    recorded_at: str

    @classmethod
    def from_domain(cls, value: Attempt) -> AttemptOutput:
        return cls(
            id=value.id,
            interview_id=value.interview_id,
            interview_item_id=value.interview_item_id,
            question_id=value.question_id,
            question_version=value.question_version,
            answer_text=value.answer_text,
            assistance_level=value.assistance_level.value,
            recorded_at=value.recorded_at,
        )


class DimensionEvaluationInputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    level: int | None
    evidence: str
    gaps: str
    improvement: str
    confidence: float

    def to_domain(self) -> DimensionEvaluationInput:
        return DimensionEvaluationInput(**self.model_dump())


class DimensionEvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    capability_name: str
    level: int | None
    evidence: str
    gaps: str
    improvement: str
    confidence: float

    @classmethod
    def from_domain(cls, value: DimensionEvaluation) -> DimensionEvaluationOutput:
        return cls(
            capability_id=value.capability_id,
            capability_name=value.capability_name,
            level=value.level,
            evidence=value.evidence,
            gaps=value.gaps,
            improvement=value.improvement,
            confidence=value.confidence,
        )


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    attempt_id: str
    interview_id: str
    standard_version_id: str
    question_id: str
    question_version: int
    summary: str
    evaluator_provenance: dict[str, Any]
    evidence_eligible: bool
    created_at: str
    dimensions: tuple[DimensionEvaluationOutput, ...]

    @classmethod
    def from_domain(cls, value: Evaluation) -> EvaluationOutput:
        return cls(
            id=value.id,
            attempt_id=value.attempt_id,
            interview_id=value.interview_id,
            standard_version_id=value.standard_version_id,
            question_id=value.question_id,
            question_version=value.question_version,
            summary=value.summary,
            evaluator_provenance=value.evaluator_provenance,
            evidence_eligible=value.evidence_eligible,
            created_at=value.created_at,
            dimensions=tuple(
                DimensionEvaluationOutput.from_domain(item) for item in value.dimensions
            ),
        )


class PracticeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question_id: str
    question_version: int
    response_text: str
    assistance_level: str
    coach_notes: str
    created_at: str
    evidence_eligible: bool = False

    @classmethod
    def from_domain(cls, value: PracticeRecord) -> PracticeOutput:
        return cls(
            id=value.id,
            question_id=value.question_id,
            question_version=value.question_version,
            response_text=value.response_text,
            assistance_level=value.assistance_level.value,
            coach_notes=value.coach_notes,
            created_at=value.created_at,
        )


class RealInterviewQuestionInputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str
    answer_summary: str = ""
    interviewer_feedback: str = ""
    topic_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    recall_confidence: float = 0.5

    def to_domain(self) -> RealInterviewQuestionInput:
        return RealInterviewQuestionInput(**self.model_dump())
