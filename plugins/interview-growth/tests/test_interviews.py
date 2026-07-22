from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from typing import cast

import pytest

from interview_growth.application.capabilities import CapabilityService
from interview_growth.application.context import ContextService
from interview_growth.application.goals import GoalService
from interview_growth.application.interviews import InterviewService
from interview_growth.application.question_bank import QuestionBankService
from interview_growth.application.real_interviews import RealInterviewService
from interview_growth.application.standards import StandardService
from interview_growth.domain.errors import DomainValidationError, VersionConflictError
from interview_growth.domain.models import (
    AssistanceLevel,
    ContextRole,
    DimensionEvaluationInput,
    InterviewItemKind,
    InterviewItemStatus,
    InterviewStatus,
    QuestionStatus,
    RealInterviewQuestionInput,
    RequirementInput,
)
from interview_growth.hook_cli import main as hook_main
from interview_growth.persistence.database import connect_database


def _rubric() -> dict[str, object]:
    return {
        "evaluation_intent": "Assess architecture reasoning.",
        "expected_evidence": ["Explains components and trade-offs."],
        "critical_omissions": ["No failure handling."],
        "level_anchors": {
            "0": "Fundamentally incorrect.",
            "1": "Names components without reasoning.",
            "2": "Partial design with important gaps.",
            "3": "Meets the target role requirement.",
            "4": "Handles advanced trade-offs and failure modes.",
        },
        "follow_up_directions": ["Probe consistency and operational failure."],
    }


def _plan() -> dict[str, object]:
    return {
        "scope": "Agent system design",
        "difficulty": "target-role",
        "question_budget": 4,
        "time_budget_minutes": 45,
        "source_strategy": "question-bank-first",
        "feedback_timing": "after-interview",
    }


def _configured_goal(
    factory: Callable[[], GoalService],
) -> tuple[GoalService, InterviewService, QuestionBankService, str, str]:
    goals = factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="goal-agent")
    goals.select_goal(session_id="session-a", goal_id=goal.id)
    standards = StandardService(goals)
    topic = standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Memory",
        description="Memory architecture.",
        parent_id=None,
        aliases=(),
        idempotency_key="topic-memory",
    )
    capability = standards.create_capability(
        session_id="session-a",
        canonical_name="System Design",
        description="Design production systems.",
        idempotency_key="cap-design",
    )
    draft = standards.create_draft(
        session_id="session-a",
        role_profile={"role": "Agent Engineer", "level": "Senior"},
        source_ids=(),
        topic_requirements=(RequirementInput(topic.id, 3, 1, True, 2),),
        capability_requirements=(RequirementInput(capability.id, 3, 1, True, 2),),
        idempotency_key="draft-v1",
    )
    standards.approve_draft(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        idempotency_key="approve-v1",
    )
    questions = QuestionBankService(goals)
    captured = questions.capture(
        session_id="session-a",
        prompt="Design memory for a production agent.",
        source="generated",
        topic_ids=(topic.id,),
        capability_ids=(capability.id,),
        idempotency_key="capture-main",
    )
    prepared = questions.prepare_version(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=1,
        prompt=captured.version.prompt,
        intent="Assess memory architecture.",
        rubric=_rubric(),
        topic_ids=(topic.id,),
        capability_ids=(capability.id,),
        idempotency_key="prepare-main",
    )
    return goals, InterviewService(goals), questions, prepared.id, capability.id


def _dimension(capability_id: str, *, confidence: float = 0.9) -> DimensionEvaluationInput:
    return DimensionEvaluationInput(
        capability_id=capability_id,
        level=3,
        evidence="Separated working memory from durable retrieval.",
        gaps="Did not quantify retrieval latency.",
        improvement="Add latency budgets and failure recovery.",
        confidence=confidence,
    )


def _provenance() -> dict[str, object]:
    return {
        "evaluator": "host-agent",
        "host": "codex",
        "model": "test-model",
        "prompt_version": "evaluator-v1",
    }


def _add_assessable_question(
    questions: QuestionBankService,
    *,
    suffix: str,
    topic_ids: tuple[str, ...],
    capability_id: str,
) -> str:
    captured = questions.capture(
        session_id="session-a",
        prompt=f"Design a production agent memory system: scenario {suffix}.",
        source="generated",
        topic_ids=topic_ids,
        capability_ids=(capability_id,),
        idempotency_key=f"capture-{suffix}",
    )
    prepared = questions.prepare_version(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=1,
        prompt=captured.version.prompt,
        intent="Assess architecture under a different scenario.",
        rubric=_rubric(),
        topic_ids=topic_ids,
        capability_ids=(capability_id,),
        idempotency_key=f"prepare-{suffix}",
    )
    return prepared.id


def test_interview_plan_preserves_structured_design_metadata(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    _, interviews, _, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    plan = {
        **_plan(),
        "capability_coverage": [capability_id],
        "critical_requirement_coverage": [capability_id],
        "question_mix": {"technical": 1},
        "debrief_mode": "structured",
    }

    started = interviews.start(
        session_id="session-a",
        plan=plan,
        question_ids=(question_id,),
        idempotency_key="structured-plan",
    )

    assert started.plan == plan
    assert interviews.get_state(
        session_id="session-a", interview_id=started.id
    ).plan == plan


def test_raw_attempt_survives_evaluation_failure_and_versions_stay_frozen(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    _, interviews, questions, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="interview-start",
    )
    item = started.items[0]
    assert item.question_version == 2

    questions.prepare_version(
        session_id="session-a",
        question_id=question_id,
        expected_current_version=2,
        prompt="A materially revised memory design question.",
        intent="Assess revised architecture reasoning.",
        rubric=_rubric(),
        topic_ids=questions.get_history(
            session_id="session-a", question_id=question_id
        )[-1].topic_ids,
        capability_ids=(capability_id,),
        idempotency_key="prepare-main-v3",
    )

    attempt = interviews.record_attempt(
        session_id="session-a",
        interview_id=started.id,
        interview_item_id=item.id,
        expected_revision=1,
        answer_text="Use working memory plus durable vector and event stores.",
        assistance_level=AssistanceLevel.INDEPENDENT,
        idempotency_key="attempt-main",
    )
    assert attempt.question_version == 2
    assert interviews.get_state(
        session_id="session-a", interview_id=started.id
    ).items[0].status is InterviewItemStatus.ANSWERED

    with pytest.raises(DomainValidationError):
        interviews.submit_evaluation(
            session_id="session-a",
            interview_id=started.id,
            attempt_id=attempt.id,
            expected_revision=2,
            summary="Invalid evaluator output.",
            dimensions=(),
            evaluator_provenance=_provenance(),
            idempotency_key="bad-evaluation",
        )

    recovered = interviews.evaluator_context(
        session_id="session-a",
        interview_id=started.id,
        attempt_id=attempt.id,
    )
    recovered_attempt = cast(dict[str, object], recovered["attempt"])
    frozen_question = cast(dict[str, object], recovered["frozen_question"])
    assert recovered_attempt["answer_text"] == attempt.answer_text
    assert frozen_question["version"] == 2

    evaluation = interviews.submit_evaluation(
        session_id="session-a",
        interview_id=started.id,
        attempt_id=attempt.id,
        expected_revision=2,
        summary="Meets the target with a few operational gaps.",
        dimensions=(_dimension(capability_id),),
        evaluator_provenance=_provenance(),
        idempotency_key="evaluation-main",
    )
    assert evaluation.evidence_eligible
    assert evaluation.question_version == 2
    final_state = interviews.get_state(
        session_id="session-a", interview_id=started.id
    )
    assert final_state.revision == 3
    assert final_state.items[0].status is InterviewItemStatus.EVALUATED


def test_followup_is_first_class_and_links_to_triggering_attempt(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    _, interviews, questions, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    parent = started.items[0]
    attempt = interviews.record_attempt(
        session_id="session-a",
        interview_id=started.id,
        interview_item_id=parent.id,
        expected_revision=1,
        answer_text="Use a vector database for every memory.",
        assistance_level=AssistanceLevel.INDEPENDENT,
        idempotency_key="attempt",
    )
    parent_version = questions.get_history(
        session_id="session-a", question_id=question_id
    )[-1]
    captured = questions.capture(
        session_id="session-a",
        prompt="When would a vector database be the wrong memory store?",
        source="adaptive-followup",
        topic_ids=parent_version.topic_ids,
        capability_ids=(capability_id,),
        idempotency_key="capture-followup",
    )
    followup_question = questions.prepare_version(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=1,
        prompt=captured.version.prompt,
        intent="Probe storage trade-offs.",
        rubric=_rubric(),
        topic_ids=parent_version.topic_ids,
        capability_ids=(capability_id,),
        idempotency_key="prepare-followup",
    )
    state = interviews.register_followup(
        session_id="session-a",
        interview_id=started.id,
        question_id=followup_question.id,
        parent_item_id=parent.id,
        trigger_attempt_id=attempt.id,
        expected_revision=2,
        idempotency_key="register-followup",
    )

    followup = state.items[-1]
    assert followup.kind is InterviewItemKind.FOLLOWUP
    assert followup.parent_item_id == parent.id
    assert followup.trigger_attempt_id == attempt.id
    assert followup.question_id == followup_question.id


def test_pause_resume_finish_and_stale_revision_guard(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    _, interviews, _, question_id, _ = _configured_goal(goal_service_factory)
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    paused = interviews.pause(
        session_id="session-a",
        interview_id=started.id,
        expected_revision=1,
        idempotency_key="pause",
    )
    assert paused.status is InterviewStatus.PAUSED

    with pytest.raises(VersionConflictError):
        interviews.resume(
            session_id="session-a",
            interview_id=started.id,
            expected_revision=1,
            idempotency_key="stale-resume",
        )

    resumed = interviews.resume(
        session_id="session-a",
        interview_id=started.id,
        expected_revision=2,
        idempotency_key="resume",
    )
    finished = interviews.finish(
        session_id="session-a",
        interview_id=started.id,
        expected_revision=3,
        outcome_summary="Ended early by user request.",
        aborted=False,
        idempotency_key="finish",
    )
    assert resumed.status is InterviewStatus.IN_PROGRESS
    assert finished.status is InterviewStatus.COMPLETED
    assert finished.items[0].status is InterviewItemStatus.SKIPPED


def test_assisted_attempt_and_coached_practice_never_become_eligible(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    _, interviews, _, question_id, capability_id = _configured_goal(goal_service_factory)
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    attempt = interviews.record_attempt(
        session_id="session-a",
        interview_id=started.id,
        interview_item_id=started.items[0].id,
        expected_revision=1,
        answer_text="I used the hint and then proposed a layered memory system.",
        assistance_level=AssistanceLevel.HINTED,
        idempotency_key="hinted-attempt",
    )
    evaluation = interviews.submit_evaluation(
        session_id="session-a",
        interview_id=started.id,
        attempt_id=attempt.id,
        expected_revision=2,
        summary="Good answer after assistance.",
        dimensions=(_dimension(capability_id),),
        evaluator_provenance=_provenance(),
        idempotency_key="hinted-evaluation",
    )
    practice = interviews.record_practice(
        session_id="session-a",
        question_id=question_id,
        response_text="A revised answer after coaching.",
        assistance_level=AssistanceLevel.COACHED,
        coach_notes="Prompted the user to compare storage types.",
        idempotency_key="coached-practice",
    )
    assert not evaluation.evidence_eligible
    assert practice.assistance_level is AssistanceLevel.COACHED

    with pytest.raises(DomainValidationError):
        interviews.record_practice(
            session_id="session-a",
            question_id=question_id,
            response_text="Independent answer incorrectly sent to coach mode.",
            assistance_level=AssistanceLevel.INDEPENDENT,
            coach_notes="No assistance.",
            idempotency_key="invalid-practice",
        )


def test_role_contexts_separate_interviewing_evaluation_and_coaching(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, interviews, _, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    interviewer_packet = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.INTERVIEWER,
        task="ask_next",
        interview_id=started.id,
    )
    interviewer_context = repr(interviewer_packet.payload["interview"])
    assert "Design memory for a production agent." in interviewer_context
    assert "level_anchors" not in interviewer_context
    assert "expected_evidence" not in interviewer_context
    assert "answer_text" not in interviewer_context

    attempt = interviews.record_attempt(
        session_id="session-a",
        interview_id=started.id,
        interview_item_id=started.items[0].id,
        expected_revision=1,
        answer_text="Use working memory and durable retrieval with retention policies.",
        assistance_level=AssistanceLevel.INDEPENDENT,
        idempotency_key="attempt",
    )
    evaluator_packet = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.EVALUATOR,
        task="evaluate",
        interview_id=started.id,
        attempt_id=attempt.id,
    )
    evaluator_context = repr(evaluator_packet.payload["evaluation_context"])
    assert attempt.answer_text in evaluator_context
    assert "level_anchors" in evaluator_context
    assert "'evaluation':" not in evaluator_context

    interviews.submit_evaluation(
        session_id="session-a",
        interview_id=started.id,
        attempt_id=attempt.id,
        expected_revision=2,
        summary="Meets the role with operational gaps.",
        dimensions=(_dimension(capability_id),),
        evaluator_provenance=_provenance(),
        idempotency_key="evaluation",
    )
    coach_packet = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.COACH,
        task="coach",
        interview_id=started.id,
        attempt_id=attempt.id,
    )
    coach_context = repr(coach_packet.payload["coach_context"])
    assert "operational gaps" in coach_context
    assert "must be stored as assisted practice" in coach_context


def test_precompact_hook_accepts_explicit_pi_session_arguments(
    goal_service_factory: Callable[[], GoalService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goals, interviews, _, question_id, _ = _configured_goal(goal_service_factory)
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    monkeypatch.setenv("INTERVIEW_GROWTH_DATA_DIR", str(goals.paths.root))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "interview-growth-hook",
            "checkpoint",
            "--session-id",
            "session-a",
            "--event",
            "pi:threshold",
        ],
    )

    hook_main()

    with connect_database(goals.paths.goal_database(goals.get_current_goal(
        session_id="session-a"
    ).id)) as connection:
        rows = connection.execute(
            """
            SELECT reason FROM interview_checkpoints
            WHERE interview_id = ? ORDER BY created_at, id
            """,
            (started.id,),
        ).fetchall()
    assert [row["reason"] for row in rows] == ["interview_started", "hook:pi:threshold"]


def test_precompact_hook_checkpoints_active_interview_without_parsing_chat(
    goal_service_factory: Callable[[], GoalService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goals, interviews, _, question_id, _ = _configured_goal(goal_service_factory)
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    monkeypatch.setenv("INTERVIEW_GROWTH_DATA_DIR", str(goals.paths.root))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "session-a",
                    "hook_event_name": "PreCompact",
                    "transcript": "This field must not be parsed for business events.",
                }
            )
        ),
    )
    monkeypatch.setattr(sys, "argv", ["interview-growth-hook", "checkpoint"])

    hook_main()

    with connect_database(goals.paths.goal_database(goals.get_current_goal(
        session_id="session-a"
    ).id)) as connection:
        rows = connection.execute(
            """
            SELECT reason FROM interview_checkpoints
            WHERE interview_id = ? ORDER BY created_at, id
            """,
            (started.id,),
        ).fetchall()
    assert [row["reason"] for row in rows] == ["interview_started", "hook:PreCompact"]


def test_interview_state_is_unavailable_after_switching_to_another_goal(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, interviews, _, question_id, _ = _configured_goal(goal_service_factory)
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="start",
    )
    other = goals.create_goal(name="LLM Infra", idempotency_key="goal-infra")
    goals.select_goal(session_id="session-a", goal_id=other.id)

    with pytest.raises(DomainValidationError):
        interviews.get_state(session_id="session-a", interview_id=started.id)


def test_dashboard_requires_coverage_and_excludes_open_disputes(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, interviews, questions, first_question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    topic_ids = questions.get_history(
        session_id="session-a", question_id=first_question_id
    )[-1].topic_ids
    question_ids = (
        first_question_id,
        _add_assessable_question(
            questions,
            suffix="coverage-two",
            topic_ids=topic_ids,
            capability_id=capability_id,
        ),
        _add_assessable_question(
            questions,
            suffix="coverage-three",
            topic_ids=topic_ids,
            capability_id=capability_id,
        ),
    )
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=question_ids,
        idempotency_key="dashboard-interview",
    )
    revision = 1
    evaluation_ids: list[str] = []
    for index, item in enumerate(started.items, start=1):
        attempt = interviews.record_attempt(
            session_id="session-a",
            interview_id=started.id,
            interview_item_id=item.id,
            expected_revision=revision,
            answer_text=f"Independent architecture answer {index} with trade-offs.",
            assistance_level=AssistanceLevel.INDEPENDENT,
            idempotency_key=f"dashboard-attempt-{index}",
        )
        revision += 1
        evaluation = interviews.submit_evaluation(
            session_id="session-a",
            interview_id=started.id,
            attempt_id=attempt.id,
            expected_revision=revision,
            summary="Meets the target requirement.",
            dimensions=(_dimension(capability_id),),
            evaluator_provenance=_provenance(),
            idempotency_key=f"dashboard-evaluation-{index}",
        )
        revision += 1
        evaluation_ids.append(evaluation.id)

    capabilities = CapabilityService(
        goals, clock=lambda: "2026-07-19T12:00:00.000Z"
    )
    dashboard = capabilities.dashboard(session_id="session-a")
    assert dashboard["readiness"] == "ready"
    requirements = cast(list[dict[str, object]], dashboard["requirements"])
    assert {item["status"] for item in requirements} == {"meets"}
    assert "score" not in dashboard

    dispute = capabilities.dispute(
        session_id="session-a",
        evaluation_id=evaluation_ids[0],
        reason="The evaluator overlooked a material trade-off.",
        idempotency_key="dispute-first",
    )
    assert dispute["status"] == "open"
    assert capabilities.dashboard(session_id="session-a")["readiness"] == (
        "evidence_insufficient"
    )

    reassessed = capabilities.submit_reassessment(
        session_id="session-a",
        dispute_id=cast(str, dispute["id"]),
        summary="Blind reassessment confirms the target level.",
        dimensions=(_dimension(capability_id),),
        evaluator_provenance={**_provenance(), "evaluator": "fresh-evaluator"},
        idempotency_key="reassess-first",
    )
    assert reassessed["reassessment_id"] is not None
    resolved = capabilities.resolve_dispute(
        session_id="session-a",
        dispute_id=cast(str, dispute["id"]),
        resolution="reassessment",
        notes="Use the blind reassessment as effective evidence.",
        idempotency_key="resolve-first",
    )
    assert resolved["resolution"] == "reassessment"
    assert capabilities.dashboard(session_id="session-a")["readiness"] == "ready"


def test_gap_prescription_schedules_only_a_different_question(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, interviews, questions, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    started = interviews.start(
        session_id="session-a",
        plan=_plan(),
        question_ids=(question_id,),
        idempotency_key="training-interview",
    )
    attempt = interviews.record_attempt(
        session_id="session-a",
        interview_id=started.id,
        interview_item_id=started.items[0].id,
        expected_revision=1,
        answer_text="Independent but incomplete architecture answer.",
        assistance_level=AssistanceLevel.INDEPENDENT,
        idempotency_key="training-attempt",
    )
    interviews.submit_evaluation(
        session_id="session-a",
        interview_id=started.id,
        attempt_id=attempt.id,
        expected_revision=2,
        summary="One useful but insufficient evidence point.",
        dimensions=(_dimension(capability_id),),
        evaluator_provenance=_provenance(),
        idempotency_key="training-evaluation",
    )
    capabilities = CapabilityService(
        goals, clock=lambda: "2026-07-19T12:00:00.000Z"
    )
    prescription = capabilities.create_prescription(
        session_id="session-a",
        subject_type="capability",
        subject_id=capability_id,
        action_plan="Practice latency budgets, then explain failure recovery unaided.",
        idempotency_key="training-prescription",
    )
    assert capabilities.next_prescription(session_id="session-a") == prescription

    with pytest.raises(DomainValidationError):
        capabilities.schedule_retest(
            session_id="session-a",
            prescription_id=cast(str, prescription["id"]),
            question_id=question_id,
            due_at="2026-07-26T12:00:00.000Z",
            idempotency_key="same-question-retest",
        )

    topic_ids = questions.get_history(
        session_id="session-a", question_id=question_id
    )[-1].topic_ids
    different_question_id = _add_assessable_question(
        questions,
        suffix="retest-different",
        topic_ids=topic_ids,
        capability_id=capability_id,
    )
    retest = capabilities.schedule_retest(
        session_id="session-a",
        prescription_id=cast(str, prescription["id"]),
        question_id=different_question_id,
        due_at="2026-07-26T12:00:00.000Z",
        idempotency_key="different-question-retest",
    )
    assert retest["status"] == "scheduled"
    assert retest["question_id"] == different_question_id


def test_real_interview_review_adds_candidates_without_formal_evidence(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _, questions, question_id, capability_id = _configured_goal(
        goal_service_factory
    )
    topic_ids = questions.get_history(
        session_id="session-a", question_id=question_id
    )[-1].topic_ids
    service = RealInterviewService(
        goals, clock=lambda: "2026-07-20T12:00:00.000Z"
    )
    inputs = (
        RealInterviewQuestionInput(
            prompt="How would you choose a memory store for an agent?",
            answer_summary="I compared vector search with an event store.",
            interviewer_feedback="Asked for more operational detail.",
            topic_ids=topic_ids,
            capability_ids=(capability_id,),
            recall_confidence=0.7,
        ),
        RealInterviewQuestionInput(
            prompt="How do you debug an unfamiliar GPU kernel failure?",
            answer_summary="I described logs and reduction.",
            interviewer_feedback="No explicit feedback.",
            topic_ids=(),
            capability_ids=(),
            recall_confidence=0.4,
        ),
    )
    review = service.record(
        session_id="session-a",
        company="Example AI",
        role_title="Agent Engineer",
        round_name="System Design",
        interviewed_at="2026-07-20T09:00:00.000Z",
        result="pending",
        overall_notes="The interview exposed one uncovered area.",
        questions=inputs,
        idempotency_key="real-review-one",
    )
    memories = cast(list[dict[str, object]], review["questions"])
    assert review["evidence_eligible"] is False
    assert [item["coverage_status"] for item in memories] == ["mapped", "unmapped"]
    assert review["blind_spot_count"] == 1
    assert service.record(
        session_id="session-a",
        company="Example AI",
        role_title="Agent Engineer",
        round_name="System Design",
        interviewed_at="2026-07-20T09:00:00.000Z",
        result="pending",
        overall_notes="The interview exposed one uncovered area.",
        questions=inputs,
        idempotency_key="real-review-one",
    )["id"] == review["id"]
    candidates = questions.search(
        session_id="session-a", query="", status=QuestionStatus.PENDING
    )
    assert len(candidates) == 2
    assert service.list(session_id="session-a")[0]["id"] == review["id"]
