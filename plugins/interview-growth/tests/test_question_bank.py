from __future__ import annotations

from collections.abc import Callable

import pytest

from interview_growth.application.goals import GoalService
from interview_growth.application.question_bank import QuestionBankService
from interview_growth.application.standards import StandardService
from interview_growth.domain.errors import VersionConflictError
from interview_growth.domain.models import QuestionStatus


def _taxonomy(factory: Callable[[], GoalService]) -> tuple[GoalService, str, str]:
    goals = factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="goal-agent")
    goals.select_goal(session_id="session-a", goal_id=goal.id)
    standards = StandardService(goals)
    topic = standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Memory",
        description="Memory architectures.",
        parent_id=None,
        aliases=("Memory",),
        idempotency_key="topic-memory",
    )
    capability = standards.create_capability(
        session_id="session-a",
        canonical_name="Trade-off Analysis",
        description="Compare design choices.",
        idempotency_key="cap-tradeoff",
    )
    return goals, topic.id, capability.id


def _rubric() -> dict[str, object]:
    return {
        "evaluation_intent": "Assess memory architecture reasoning.",
        "expected_evidence": ["Separates working and long-term memory."],
        "critical_omissions": ["No retrieval strategy."],
        "level_anchors": {
            "0": "Fundamentally incorrect.",
            "1": "Names storage only.",
            "2": "Partial design with major gaps.",
            "3": "Meets the target role requirement.",
            "4": "Explains advanced operational trade-offs.",
        },
        "follow_up_directions": ["Probe consistency and retention."],
    }


def test_question_capture_prepare_search_and_retire_preserve_history(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, topic_id, capability_id = _taxonomy(goal_service_factory)
    questions = QuestionBankService(goals)
    captured = questions.capture(
        session_id="session-a",
        prompt="How would you design memory for a production agent?",
        source="user",
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="capture-memory",
    )
    replay = questions.capture(
        session_id="session-a",
        prompt="How would you design memory for a production agent?",
        source="user",
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="capture-memory",
    )
    assert replay == captured
    assert captured.status is QuestionStatus.PENDING

    prepared = questions.prepare_version(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=1,
        prompt=captured.version.prompt,
        intent="Evaluate architecture and trade-off reasoning.",
        rubric=_rubric(),
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="prepare-memory-v2",
    )
    assert prepared.status is QuestionStatus.ASSESSABLE
    assert prepared.current_version == 2
    assert len(questions.get_history(session_id="session-a", question_id=captured.id)) == 2
    assert questions.search(
        session_id="session-a",
        query="production agent",
        topic_id=topic_id,
        status=QuestionStatus.ASSESSABLE,
    ) == (prepared,)

    retired = questions.retire(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=2,
        idempotency_key="retire-memory",
    )
    assert retired.status is QuestionStatus.RETIRED
    assert len(questions.get_history(session_id="session-a", question_id=captured.id)) == 2


def test_question_prepare_rejects_stale_expected_version(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, topic_id, capability_id = _taxonomy(goal_service_factory)
    questions = QuestionBankService(goals)
    captured = questions.capture(
        session_id="session-a",
        prompt="Explain memory retrieval strategies.",
        source="user",
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="capture",
    )
    questions.prepare_version(
        session_id="session-a",
        question_id=captured.id,
        expected_current_version=1,
        prompt=captured.version.prompt,
        intent="Evaluate retrieval trade-offs.",
        rubric=_rubric(),
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="prepare-v2",
    )

    with pytest.raises(VersionConflictError):
        questions.prepare_version(
            session_id="session-a",
            question_id=captured.id,
            expected_current_version=1,
            prompt="A stale edit.",
            intent="Evaluate retrieval trade-offs.",
            rubric=_rubric(),
            topic_ids=(topic_id,),
            capability_ids=(capability_id,),
            idempotency_key="stale-edit",
        )


def test_question_duplicate_suggestions_and_goal_isolation(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, topic_id, capability_id = _taxonomy(goal_service_factory)
    questions = QuestionBankService(goals)
    first = questions.capture(
        session_id="session-a",
        prompt="How would you design memory for an agent?",
        source="user",
        topic_ids=(topic_id,),
        capability_ids=(capability_id,),
        idempotency_key="capture-first",
    )
    suggestions = questions.suggest_duplicates(
        session_id="session-a",
        prompt="How would you design memory for an agent?",
    )
    assert suggestions[0].question_id == first.id
    assert suggestions[0].score == 1.0

    second_goal = goals.create_goal(name="LLM Infra", idempotency_key="goal-infra")
    goals.select_goal(session_id="session-a", goal_id=second_goal.id)
    assert questions.search(session_id="session-a") == ()
