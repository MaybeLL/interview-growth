from __future__ import annotations

from collections.abc import Callable

import pytest

from interview_growth.application.goals import GoalService
from interview_growth.application.standards import StandardService
from interview_growth.domain.errors import DomainValidationError, VersionConflictError
from interview_growth.domain.models import (
    RequirementInput,
    SourceMaterialKind,
    StandardVersion,
)


def _selected_goal(factory: Callable[[], GoalService]) -> tuple[GoalService, str]:
    goals = factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="goal-agent")
    goals.select_goal(session_id="session-a", goal_id=goal.id)
    return goals, goal.id


def test_standard_draft_approval_creates_immutable_version(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _ = _selected_goal(goal_service_factory)
    standards = StandardService(goals)
    source = standards.add_source_material(
        session_id="session-a",
        kind=SourceMaterialKind.JOB_DESCRIPTION,
        title="Senior Agent Engineer JD",
        content="Design reliable agent systems and evaluation infrastructure.",
        idempotency_key="source-jd",
    )
    topic = standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Memory",
        description="Short- and long-term memory design.",
        parent_id=None,
        aliases=("Memory",),
        idempotency_key="topic-memory",
    )
    capability = standards.create_capability(
        session_id="session-a",
        canonical_name="Trade-off Analysis",
        description="Explain competing design constraints.",
        idempotency_key="cap-tradeoff",
    )
    requirement_topic = RequirementInput(topic.id, 3, 2.0, True, 3)
    requirement_capability = RequirementInput(capability.id, 3, 1.5, True, 3)
    draft = standards.create_draft(
        session_id="session-a",
        role_profile={"role": "Agent Engineer", "level": "Senior"},
        source_ids=(source.id,),
        topic_requirements=(requirement_topic,),
        capability_requirements=(requirement_capability,),
        idempotency_key="draft-v1",
    )
    approved = standards.approve_draft(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        idempotency_key="approve-v1",
    )
    replay = standards.approve_draft(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        idempotency_key="approve-v1",
    )

    assert approved == replay
    assert approved.version_number == 1
    assert approved.source_draft_revision == 1
    assert approved.topic_requirements[0].subject_name == "Agent Memory"
    assert approved.topic_requirements[0].critical
    assert standards.get_draft(session_id="session-a", draft_id=draft.id).status == "approved"


def test_role_profile_can_be_reviewed_and_updated_before_approval(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _ = _selected_goal(goal_service_factory)
    standards = StandardService(goals)
    topic = standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Architecture",
        description="Architecture for reliable agents.",
        parent_id=None,
        aliases=(),
        idempotency_key="topic-architecture",
    )
    capability = standards.create_capability(
        session_id="session-a",
        canonical_name="Technical Communication",
        description="Explain technical decisions clearly.",
        idempotency_key="cap-communication",
    )
    draft = standards.create_draft(
        session_id="session-a",
        role_profile={"role": "Agent Engineer", "level": "Senior"},
        source_ids=(),
        topic_requirements=(RequirementInput(topic.id, 3, 1, True, 2),),
        capability_requirements=(RequirementInput(capability.id, 3, 1, True, 2),),
        idempotency_key="profile-draft",
    )

    assert standards.current_version(session_id="session-a") is None
    updated = standards.update_draft_role_profile(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        role_profile={
            "role": "  Agent Engineer  ",
            "level": "Senior",
            "company_types": ["AI platform", "AI platform"],
            "technologies": ["Python", "LLM evaluation"],
            "portfolio_required": True,
        },
        idempotency_key="profile-update",
    )
    replay = standards.update_draft_role_profile(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=1,
        role_profile={
            "role": "  Agent Engineer  ",
            "level": "Senior",
            "company_types": ["AI platform", "AI platform"],
            "technologies": ["Python", "LLM evaluation"],
            "portfolio_required": True,
        },
        idempotency_key="profile-update",
    )

    assert updated == replay
    assert updated.revision == 2
    assert updated.role_profile["role"] == "Agent Engineer"
    assert updated.role_profile["company_types"] == ["AI platform"]
    assert updated.role_profile["portfolio_required"] is True

    with pytest.raises(VersionConflictError):
        standards.update_draft_role_profile(
            session_id="session-a",
            draft_id=draft.id,
            expected_revision=1,
            role_profile={"role": "Agent Engineer", "level": "Staff"},
            idempotency_key="profile-stale-update",
        )

    approved = standards.approve_draft(
        session_id="session-a",
        draft_id=draft.id,
        expected_revision=2,
        idempotency_key="profile-approve",
    )
    assert standards.current_version(session_id="session-a") == approved

    with pytest.raises(DomainValidationError):
        standards.update_draft_role_profile(
            session_id="session-a",
            draft_id=draft.id,
            expected_revision=2,
            role_profile={"role": "Agent Engineer", "level": "Staff"},
            idempotency_key="profile-approved-update",
        )


def test_role_profile_rejects_invalid_known_fields(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _ = _selected_goal(goal_service_factory)
    standards = StandardService(goals)

    with pytest.raises(DomainValidationError, match="technologies must be a list"):
        standards.create_draft(
            session_id="session-a",
            role_profile={
                "role": "Agent Engineer",
                "level": "Senior",
                "technologies": "Python",
            },
            source_ids=(),
            topic_requirements=(),
            capability_requirements=(),
            idempotency_key="invalid-profile",
        )


def test_standard_versions_compare_requirement_changes(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _ = _selected_goal(goal_service_factory)
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

    versions: list[StandardVersion] = []
    profiles = (
        {"role": "Agent Engineer", "level": "L1", "locations": ["Remote"]},
        {"role": "Agent Engineer", "level": "L2", "technologies": ["Python"]},
    )
    for index, level in enumerate((2, 3), start=1):
        draft = standards.create_draft(
            session_id="session-a",
            role_profile=profiles[index - 1],
            source_ids=(),
            topic_requirements=(RequirementInput(topic.id, level, 1, False, 2),),
            capability_requirements=(
                RequirementInput(capability.id, level, 1, False, 2),
            ),
            idempotency_key=f"draft-{index}",
        )
        versions.append(
            standards.approve_draft(
                session_id="session-a",
                draft_id=draft.id,
                expected_revision=1,
                idempotency_key=f"approve-{index}",
            )
        )

    comparison = standards.compare_versions(
        session_id="session-a",
        older_id=versions[0].id,
        newer_id=versions[1].id,
    )
    assert comparison["role_profile_changed"] is True
    assert comparison["role_profile"] == {
        "added": {"technologies": ["Python"]},
        "removed": {"locations": ["Remote"]},
        "changed": {"level": {"older": "L1", "newer": "L2"}},
    }
    assert comparison["topic_requirements"]["changed"] == [topic.id]
    assert comparison["capability_requirements"]["changed"] == [capability.id]


def test_taxonomy_and_standard_data_are_isolated_by_current_goal(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals = goal_service_factory()
    first = goals.create_goal(name="Agent Engineer", idempotency_key="agent")
    second = goals.create_goal(name="LLM Infra", idempotency_key="infra")
    standards = StandardService(goals)

    goals.select_goal(session_id="session-a", goal_id=first.id)
    standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Memory",
        description="Memory systems.",
        parent_id=None,
        aliases=("Memory",),
        idempotency_key="same-key",
    )
    goals.select_goal(session_id="session-a", goal_id=second.id)

    assert standards.list_topics(session_id="session-a") == ()
    second_topic = standards.create_topic(
        session_id="session-a",
        canonical_name="Agent Memory",
        description="A separate copy in another target.",
        parent_id=None,
        aliases=("Memory",),
        idempotency_key="same-key",
    )
    goals.select_goal(session_id="session-a", goal_id=first.id)
    first_topic = standards.list_topics(session_id="session-a")[0]
    assert first_topic.id != second_topic.id
    assert first_topic.description == "Memory systems."


def test_topic_alias_blocks_exact_duplicate(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, _ = _selected_goal(goal_service_factory)
    standards = StandardService(goals)
    standards.create_topic(
        session_id="session-a",
        canonical_name="Retrieval Augmented Generation",
        description="RAG systems.",
        parent_id=None,
        aliases=("RAG",),
        idempotency_key="rag",
    )

    suggestions = standards.suggest_topic_duplicates(
        session_id="session-a", name="rag"
    )
    assert suggestions[0].score == 1.0
    assert suggestions[0].matched_by == "alias"

    with pytest.raises(DomainValidationError):
        standards.create_topic(
            session_id="session-a",
            canonical_name="RAG",
            description="Duplicate.",
            parent_id=None,
            aliases=(),
            idempotency_key="rag-duplicate",
        )
