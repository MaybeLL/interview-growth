"""Stable domain-operation registry used by the structured CLI adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from interview_growth.application.capabilities import CapabilityService
from interview_growth.application.context import ContextService
from interview_growth.application.goals import GoalService
from interview_growth.application.interviews import InterviewService
from interview_growth.application.portability import PortabilityService
from interview_growth.application.question_bank import QuestionBankService
from interview_growth.application.real_interviews import RealInterviewService
from interview_growth.application.standards import StandardService
from interview_growth.config import DataPaths
from interview_growth.contracts import (
    AttemptOutput,
    CapabilityListOutput,
    CapabilityOutput,
    ContextPacketOutput,
    DimensionEvaluationInputContract,
    DuplicateSuggestionOutput,
    EvaluationOutput,
    GoalListOutput,
    GoalOutput,
    InterviewOutput,
    PracticeOutput,
    QuestionDuplicateOutput,
    QuestionHistoryOutput,
    QuestionListOutput,
    QuestionOutput,
    QuestionVersionOutput,
    RealInterviewQuestionInputContract,
    RequirementInputContract,
    SourceMaterialOutput,
    StandardDraftOutput,
    StandardVersionListOutput,
    StandardVersionOutput,
    TopicListOutput,
    TopicOutput,
)
from interview_growth.domain.models import (
    AssistanceLevel,
    ContextRole,
    GoalLifecycle,
    QuestionStatus,
    SourceMaterialKind,
)

type Operation = Callable[..., Any]
OPERATIONS: dict[str, Operation] = {}


def operation(function: Operation) -> Operation:
    """Register one stable operation for CLI discovery and invocation."""

    OPERATIONS[function.__name__] = function
    return function


def _goal_service() -> GoalService:
    return GoalService(DataPaths.from_environment())


def _standard_service() -> StandardService:
    return StandardService(_goal_service())


def _question_service() -> QuestionBankService:
    return QuestionBankService(_goal_service())


def _interview_service() -> InterviewService:
    return InterviewService(_goal_service())


def _capability_dashboard_service() -> CapabilityService:
    return CapabilityService(_goal_service())


def _portability_service() -> PortabilityService:
    return PortabilityService(_goal_service())


def _real_interview_service() -> RealInterviewService:
    return RealInterviewService(_goal_service())


@operation
def goal_create(name: str, idempotency_key: str, slug: str | None = None) -> GoalOutput:
    """Create a physically isolated growth goal in configuring state."""

    goal = _goal_service().create_goal(
        name=name,
        slug=slug,
        idempotency_key=idempotency_key,
    )
    return GoalOutput.from_domain(goal)


@operation
def goal_list() -> GoalListOutput:
    """List registry-level goal summaries without reading goal-domain data."""

    goals = tuple(GoalOutput.from_domain(goal) for goal in _goal_service().list_goals())
    return GoalListOutput(goals=goals)


@operation
def goal_select(session_id: str, goal_id: str) -> GoalOutput:
    """Explicitly bind this Codex session to exactly one current growth goal."""

    goal = _goal_service().select_goal(session_id=session_id, goal_id=goal_id)
    return GoalOutput.from_domain(goal)


@operation
def goal_get_current(session_id: str) -> GoalOutput:
    """Return the single growth goal currently bound to this session."""

    goal = _goal_service().get_current_goal(session_id=session_id)
    return GoalOutput.from_domain(goal)


@operation
def goal_change_lifecycle(session_id: str, lifecycle: GoalLifecycle) -> GoalOutput:
    """Change the lifecycle of the explicitly selected current goal."""

    goal = _goal_service().change_current_goal_lifecycle(
        session_id=session_id,
        requested=lifecycle,
    )
    return GoalOutput.from_domain(goal)


@operation
def context_build(
    session_id: str,
    role: ContextRole,
    task: str,
    max_tokens: int = 1200,
    interview_id: str | None = None,
    attempt_id: str | None = None,
) -> ContextPacketOutput:
    """Build a minimal role-scoped Context Packet for the current goal."""

    goals = _goal_service()
    packet = ContextService(goals).build(
        session_id=session_id,
        role=role,
        task=task,
        max_tokens=max_tokens,
        interview_id=interview_id,
        attempt_id=attempt_id,
    )
    return ContextPacketOutput.from_domain(packet)


@operation
def source_material_add(
    session_id: str,
    kind: SourceMaterialKind,
    title: str,
    content: str,
    idempotency_key: str,
) -> SourceMaterialOutput:
    """Record a JD or explicit user constraint inside the current goal."""

    value = _standard_service().add_source_material(
        session_id=session_id,
        kind=kind,
        title=title,
        content=content,
        idempotency_key=idempotency_key,
    )
    return SourceMaterialOutput.from_domain(value)


@operation
def topic_create(
    session_id: str,
    canonical_name: str,
    idempotency_key: str,
    description: str = "",
    parent_id: str | None = None,
    aliases: list[str] | None = None,
) -> TopicOutput:
    """Create a goal-local topic after reviewing duplicate suggestions."""

    value = _standard_service().create_topic(
        session_id=session_id,
        canonical_name=canonical_name,
        description=description,
        parent_id=parent_id,
        aliases=aliases or (),
        idempotency_key=idempotency_key,
    )
    return TopicOutput.from_domain(value)


@operation
def topic_list(session_id: str, active_only: bool = True) -> TopicListOutput:
    """List the current goal's topic tree nodes."""

    values = _standard_service().list_topics(
        session_id=session_id, active_only=active_only
    )
    return TopicListOutput(topics=tuple(TopicOutput.from_domain(item) for item in values))


@operation
def topic_suggest_duplicates(
    session_id: str,
    name: str,
    limit: int = 5,
) -> tuple[DuplicateSuggestionOutput, ...]:
    """Suggest canonical topics or aliases similar to a proposed topic name."""

    return tuple(
        DuplicateSuggestionOutput.from_domain(item)
        for item in _standard_service().suggest_topic_duplicates(
            session_id=session_id, name=name, limit=limit
        )
    )


@operation
def capability_create(
    session_id: str,
    canonical_name: str,
    description: str,
    idempotency_key: str,
) -> CapabilityOutput:
    """Create a transferable evaluation dimension inside the current goal."""

    value = _standard_service().create_capability(
        session_id=session_id,
        canonical_name=canonical_name,
        description=description,
        idempotency_key=idempotency_key,
    )
    return CapabilityOutput.from_domain(value)


@operation
def capability_list(session_id: str) -> CapabilityListOutput:
    """List the current goal's capability dimensions."""

    values = _standard_service().list_capabilities(session_id=session_id)
    return CapabilityListOutput(
        capabilities=tuple(CapabilityOutput.from_domain(item) for item in values)
    )


@operation
def standard_create_draft(
    session_id: str,
    role_profile: dict[str, object],
    source_ids: list[str],
    topic_requirements: list[RequirementInputContract],
    capability_requirements: list[RequirementInputContract],
    idempotency_key: str,
) -> StandardDraftOutput:
    """Create an immutable target-standard draft for user review."""

    value = _standard_service().create_draft(
        session_id=session_id,
        role_profile=role_profile,
        source_ids=source_ids,
        topic_requirements=tuple(item.to_domain() for item in topic_requirements),
        capability_requirements=tuple(
            item.to_domain() for item in capability_requirements
        ),
        idempotency_key=idempotency_key,
    )
    return StandardDraftOutput.from_domain(value)


@operation
def standard_get_draft(session_id: str, draft_id: str) -> StandardDraftOutput:
    """Get one standard draft for review without exposing another goal."""

    return StandardDraftOutput.from_domain(
        _standard_service().get_draft(session_id=session_id, draft_id=draft_id)
    )


@operation
def standard_approve(
    session_id: str,
    draft_id: str,
    expected_revision: int,
    idempotency_key: str,
) -> StandardVersionOutput:
    """Approve a reviewed draft into a new immutable standard version."""

    value = _standard_service().approve_draft(
        session_id=session_id,
        draft_id=draft_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return StandardVersionOutput.from_domain(value)


@operation
def standard_list_versions(session_id: str) -> StandardVersionListOutput:
    """List immutable target-standard versions for the current goal."""

    values = _standard_service().list_versions(session_id=session_id)
    return StandardVersionListOutput(
        versions=tuple(StandardVersionOutput.from_domain(item) for item in values)
    )


@operation
def standard_compare_versions(
    session_id: str,
    older_id: str,
    newer_id: str,
) -> dict[str, object]:
    """Compare two standard versions from the same current goal."""

    return _standard_service().compare_versions(
        session_id=session_id, older_id=older_id, newer_id=newer_id
    )


@operation
def question_capture(
    session_id: str,
    prompt: str,
    source: str,
    idempotency_key: str,
    topic_ids: list[str] | None = None,
    capability_ids: list[str] | None = None,
) -> QuestionOutput:
    """Capture a question only after the user explicitly asks to record it."""

    value = _question_service().capture(
        session_id=session_id,
        prompt=prompt,
        source=source,
        topic_ids=topic_ids or (),
        capability_ids=capability_ids or (),
        idempotency_key=idempotency_key,
    )
    return QuestionOutput.from_domain(value)


@operation
def question_prepare_version(
    session_id: str,
    question_id: str,
    expected_current_version: int,
    prompt: str,
    intent: str,
    rubric: dict[str, object],
    topic_ids: list[str],
    capability_ids: list[str],
    idempotency_key: str,
) -> QuestionOutput:
    """Append an assessable question version with a complete predeclared rubric."""

    value = _question_service().prepare_version(
        session_id=session_id,
        question_id=question_id,
        expected_current_version=expected_current_version,
        prompt=prompt,
        intent=intent,
        rubric=rubric,
        topic_ids=topic_ids,
        capability_ids=capability_ids,
        idempotency_key=idempotency_key,
    )
    return QuestionOutput.from_domain(value)


@operation
def question_search(
    session_id: str,
    query: str = "",
    topic_id: str | None = None,
    status: QuestionStatus | None = None,
    limit: int = 20,
) -> QuestionListOutput:
    """Search current question versions in the current goal only."""

    values = _question_service().search(
        session_id=session_id,
        query=query,
        topic_id=topic_id,
        status=status,
        limit=limit,
    )
    return QuestionListOutput(
        questions=tuple(QuestionOutput.from_domain(item) for item in values)
    )


@operation
def question_get_history(session_id: str, question_id: str) -> QuestionHistoryOutput:
    """Read every immutable version of one question."""

    values = _question_service().get_history(
        session_id=session_id, question_id=question_id
    )
    return QuestionHistoryOutput(
        versions=tuple(QuestionVersionOutput.from_domain(item) for item in values)
    )


@operation
def question_suggest_duplicates(
    session_id: str,
    prompt: str,
    limit: int = 5,
) -> tuple[QuestionDuplicateOutput, ...]:
    """Suggest similar current-goal questions before capture."""

    return tuple(
        QuestionDuplicateOutput.from_domain(item)
        for item in _question_service().suggest_duplicates(
            session_id=session_id, prompt=prompt, limit=limit
        )
    )


@operation
def question_retire(
    session_id: str,
    question_id: str,
    expected_current_version: int,
    idempotency_key: str,
) -> QuestionOutput:
    """Retire a question without deleting its immutable history."""

    value = _question_service().retire(
        session_id=session_id,
        question_id=question_id,
        expected_current_version=expected_current_version,
        idempotency_key=idempotency_key,
    )
    return QuestionOutput.from_domain(value)


@operation
def interview_start(
    session_id: str,
    plan: dict[str, object],
    question_ids: list[str],
    idempotency_key: str,
) -> InterviewOutput:
    """Start a formal interview and freeze its standard and initial question versions."""

    value = _interview_service().start(
        session_id=session_id,
        plan=plan,
        question_ids=question_ids,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def interview_get_state(session_id: str, interview_id: str) -> InterviewOutput:
    """Read the versioned state and queue of one current-goal interview."""

    value = _interview_service().get_state(
        session_id=session_id, interview_id=interview_id
    )
    return InterviewOutput.from_domain(value)


@operation
def interview_register_question(
    session_id: str,
    interview_id: str,
    question_id: str,
    expected_revision: int,
    idempotency_key: str,
) -> InterviewOutput:
    """Append an assessable main question and freeze its current version."""

    value = _interview_service().register_question(
        session_id=session_id,
        interview_id=interview_id,
        question_id=question_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def followup_register(
    session_id: str,
    interview_id: str,
    question_id: str,
    parent_item_id: str,
    trigger_attempt_id: str,
    expected_revision: int,
    idempotency_key: str,
) -> InterviewOutput:
    """Register a first-class follow-up before asking it to the user."""

    value = _interview_service().register_followup(
        session_id=session_id,
        interview_id=interview_id,
        question_id=question_id,
        parent_item_id=parent_item_id,
        trigger_attempt_id=trigger_attempt_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def attempt_record(
    session_id: str,
    interview_id: str,
    interview_item_id: str,
    expected_revision: int,
    answer_text: str,
    assistance_level: AssistanceLevel,
    idempotency_key: str,
) -> AttemptOutput:
    """Persist the raw answer before any evaluator inference is attempted."""

    value = _interview_service().record_attempt(
        session_id=session_id,
        interview_id=interview_id,
        interview_item_id=interview_item_id,
        expected_revision=expected_revision,
        answer_text=answer_text,
        assistance_level=assistance_level,
        idempotency_key=idempotency_key,
    )
    return AttemptOutput.from_domain(value)


@operation
def evaluation_submit(
    session_id: str,
    interview_id: str,
    attempt_id: str,
    expected_revision: int,
    summary: str,
    dimensions: list[DimensionEvaluationInputContract],
    evaluator_provenance: dict[str, object],
    idempotency_key: str,
) -> EvaluationOutput:
    """Append a rubric-bound evaluation after the raw attempt is safely stored."""

    value = _interview_service().submit_evaluation(
        session_id=session_id,
        interview_id=interview_id,
        attempt_id=attempt_id,
        expected_revision=expected_revision,
        summary=summary,
        dimensions=tuple(item.to_domain() for item in dimensions),
        evaluator_provenance=evaluator_provenance,
        idempotency_key=idempotency_key,
    )
    return EvaluationOutput.from_domain(value)


@operation
def interview_checkpoint(
    session_id: str,
    interview_id: str,
    expected_revision: int,
    reason: str,
    idempotency_key: str,
) -> InterviewOutput:
    """Persist a deterministic recovery checkpoint for the current interview revision."""

    value = _interview_service().checkpoint(
        session_id=session_id,
        interview_id=interview_id,
        expected_revision=expected_revision,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def interview_pause(
    session_id: str,
    interview_id: str,
    expected_revision: int,
    idempotency_key: str,
) -> InterviewOutput:
    """Pause an active interview while preserving its queue and checkpoints."""

    value = _interview_service().pause(
        session_id=session_id,
        interview_id=interview_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def interview_resume(
    session_id: str,
    interview_id: str,
    expected_revision: int,
    idempotency_key: str,
) -> InterviewOutput:
    """Resume a paused interview from its persisted state."""

    value = _interview_service().resume(
        session_id=session_id,
        interview_id=interview_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def interview_finish(
    session_id: str,
    interview_id: str,
    expected_revision: int,
    outcome_summary: str,
    idempotency_key: str,
    aborted: bool = False,
) -> InterviewOutput:
    """Complete or abort an interview and preserve all recorded history."""

    value = _interview_service().finish(
        session_id=session_id,
        interview_id=interview_id,
        expected_revision=expected_revision,
        outcome_summary=outcome_summary,
        aborted=aborted,
        idempotency_key=idempotency_key,
    )
    return InterviewOutput.from_domain(value)


@operation
def practice_record(
    session_id: str,
    question_id: str,
    response_text: str,
    assistance_level: AssistanceLevel,
    coach_notes: str,
    idempotency_key: str,
) -> PracticeOutput:
    """Store hinted or coached practice that can never count as independent evidence."""

    value = _interview_service().record_practice(
        session_id=session_id,
        question_id=question_id,
        response_text=response_text,
        assistance_level=assistance_level,
        coach_notes=coach_notes,
        idempotency_key=idempotency_key,
    )
    return PracticeOutput.from_domain(value)


@operation
def dashboard_get(session_id: str) -> dict[str, Any]:
    """Show evidence-backed readiness, coverage, critical gates, gaps, and next actions."""

    return _capability_dashboard_service().dashboard(session_id=session_id)


@operation
def evidence_get(session_id: str) -> dict[str, Any]:
    """List only effective evidence under the current approved standard."""

    return _capability_dashboard_service().evidence(session_id=session_id)


@operation
def gap_list(session_id: str) -> list[dict[str, Any]]:
    """List current readiness gaps without inventing a percentage score."""

    return _capability_dashboard_service().gaps(session_id=session_id)


@operation
def evaluation_dispute(
    session_id: str,
    evaluation_id: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Open a dispute and exclude the evaluation until blind reassessment is resolved."""

    return _capability_dashboard_service().dispute(
        session_id=session_id,
        evaluation_id=evaluation_id,
        reason=reason,
        idempotency_key=idempotency_key,
    )


@operation
def evaluation_submit_reassessment(
    session_id: str,
    dispute_id: str,
    summary: str,
    dimensions: list[DimensionEvaluationInputContract],
    evaluator_provenance: dict[str, object],
    idempotency_key: str,
) -> dict[str, Any]:
    """Submit an independently produced blind reassessment for an open dispute."""

    return _capability_dashboard_service().submit_reassessment(
        session_id=session_id,
        dispute_id=dispute_id,
        summary=summary,
        dimensions=tuple(item.to_domain() for item in dimensions),
        evaluator_provenance=evaluator_provenance,
        idempotency_key=idempotency_key,
    )


@operation
def evaluation_resolve_dispute(
    session_id: str,
    dispute_id: str,
    resolution: str,
    notes: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Resolve a dispute by selecting original, reassessment, or withdrawn."""

    return _capability_dashboard_service().resolve_dispute(
        session_id=session_id,
        dispute_id=dispute_id,
        resolution=resolution,
        notes=notes,
        idempotency_key=idempotency_key,
    )


@operation
def prescription_create(
    session_id: str,
    subject_type: str,
    subject_id: str,
    action_plan: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Freeze a current evidence gap into a concrete training prescription."""

    return _capability_dashboard_service().create_prescription(
        session_id=session_id,
        subject_type=subject_type,
        subject_id=subject_id,
        action_plan=action_plan,
        idempotency_key=idempotency_key,
    )


@operation
def prescription_get_next(session_id: str) -> dict[str, Any] | None:
    """Return the oldest active training prescription for the current goal."""

    return _capability_dashboard_service().next_prescription(session_id=session_id)


@operation
def retest_schedule(
    session_id: str,
    prescription_id: str,
    question_id: str,
    due_at: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Schedule a retest that covers the gap and uses a different evidence question."""

    return _capability_dashboard_service().schedule_retest(
        session_id=session_id,
        prescription_id=prescription_id,
        question_id=question_id,
        due_at=due_at,
        idempotency_key=idempotency_key,
    )


@operation
def real_interview_record(
    session_id: str,
    company: str,
    role_title: str,
    round_name: str,
    interviewed_at: str,
    result: str,
    overall_notes: str,
    questions: list[RealInterviewQuestionInputContract],
    idempotency_key: str,
) -> dict[str, Any]:
    """Record a real interview review as low-confidence, non-scoring memory."""

    return _real_interview_service().record(
        session_id=session_id,
        company=company,
        role_title=role_title,
        round_name=round_name,
        interviewed_at=interviewed_at,
        result=result,
        overall_notes=overall_notes,
        questions=tuple(item.to_domain() for item in questions),
        idempotency_key=idempotency_key,
    )


@operation
def real_interview_get(session_id: str, review_id: str) -> dict[str, Any]:
    """Get one real interview review and its coverage blind spots."""

    return _real_interview_service().get(
        session_id=session_id, review_id=review_id
    )


@operation
def real_interview_list(
    session_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """List recent real interview reviews for the current goal."""

    return _real_interview_service().list(session_id=session_id, limit=limit)


@operation
def goal_backup(
    session_id: str, reason: str, idempotency_key: str
) -> dict[str, Any]:
    """Create and verify a private goal-level SQLite backup."""

    return _portability_service().backup(
        session_id=session_id, reason=reason, idempotency_key=idempotency_key
    )


@operation
def goal_list_backups(session_id: str) -> list[dict[str, Any]]:
    """List verified backup metadata for the current goal."""

    return _portability_service().list_backups(session_id=session_id)


@operation
def goal_restore(
    session_id: str,
    backup_id: str,
    confirm_goal_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Restore a paused/ended/archived goal after creating a safety backup."""

    return _portability_service().restore(
        session_id=session_id,
        backup_id=backup_id,
        confirm_goal_id=confirm_goal_id,
        idempotency_key=idempotency_key,
    )


@operation
def goal_export(
    session_id: str, output_path: str, idempotency_key: str
) -> dict[str, Any]:
    """Explicitly export the current goal as SQLite plus JSON/Markdown in .igx."""

    return _portability_service().export(
        session_id=session_id,
        output_path=output_path,
        idempotency_key=idempotency_key,
    )


@operation
def goal_import(
    package_path: str, idempotency_key: str, name: str | None = None
) -> GoalOutput:
    """Import a verified .igx package as a new physically isolated goal."""

    return GoalOutput.from_domain(
        _portability_service().import_package(
            package_path=package_path,
            name=name,
            idempotency_key=idempotency_key,
        )
    )


@operation
def goal_delete(
    session_id: str,
    backup_id: str,
    confirm_goal_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Remove an archived goal from the app after backup, moving data to app trash."""

    return _portability_service().delete_to_trash(
        session_id=session_id,
        backup_id=backup_id,
        confirm_goal_id=confirm_goal_id,
        idempotency_key=idempotency_key,
    )
