from __future__ import annotations

from collections.abc import Callable

from interview_growth.application.context import ContextService
from interview_growth.application.goals import GoalService
from interview_growth.application.standards import StandardService
from interview_growth.domain.models import ContextRole, RequirementInput


def test_context_packet_contains_only_current_goal_and_no_paths(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals = goal_service_factory()
    current = goals.create_goal(name="Agent Engineer", idempotency_key="agent")
    other = goals.create_goal(name="LLM Infra", idempotency_key="infra")
    goals.select_goal(session_id="session-a", goal_id=current.id)

    packet = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.INTERVIEWER,
        task="session_resume",
    )
    serialized = repr(packet)

    assert packet.goal_binding["goal_id"] == current.id
    assert packet.provenance["source_goal_ids"] == [current.id]
    assert packet.packet_version == 3
    assert packet.payload["allowed_actions"] == [
        "read_target_requirements",
        "search_assessable_questions",
    ]
    assert packet.payload["question_counts"] == {
        "pending": 0,
        "assessable": 0,
        "retired": 0,
    }
    assert other.id not in serialized
    assert "goal.sqlite" not in serialized


def test_goal_manager_receives_m1_configuration_actions(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals = goal_service_factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="agent")
    goals.select_goal(session_id="session-a", goal_id=goal.id)

    packet = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.GOAL_MANAGER,
        task="manage_goal",
        max_tokens=512,
    )

    assert packet.budget == {"max_tokens": 512}
    assert packet.payload["allowed_actions"] == [
        "read_goal_summary",
        "change_goal_lifecycle",
        "manage_target_standard",
        "manage_taxonomy",
    ]


def test_approved_standard_context_is_role_scoped_and_contains_no_rubric(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals = goal_service_factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="agent")
    goals.select_goal(session_id="session-a", goal_id=goal.id)
    standards = StandardService(goals)
    topic = standards.create_topic(
        session_id="session-a",
        canonical_name="RAG",
        description="Retrieval augmented generation.",
        parent_id=None,
        aliases=(),
        idempotency_key="topic-rag",
    )
    capability = standards.create_capability(
        session_id="session-a",
        canonical_name="System Design",
        description="Design complete systems.",
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
    standard = standards.approve_draft(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        idempotency_key="approve-v1",
    )

    evaluator = ContextService(goals).build(
        session_id="session-a",
        role=ContextRole.EVALUATOR,
        task="evaluate_answer",
    )
    serialized_standard = repr(evaluator.payload["target_standard"])
    assert evaluator.payload["target_standard"]["version_id"] == standard.id
    assert "question_counts" not in evaluator.payload
    assert "rubric" not in serialized_standard
    assert "expected_evidence" not in serialized_standard
