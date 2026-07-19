from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

import pytest

from interview_growth.application.goals import GoalService
from interview_growth.config import DataPaths
from interview_growth.domain.errors import (
    IdempotencyConflictError,
    InvalidLifecycleTransitionError,
    NoCurrentGoalError,
)
from interview_growth.domain.models import GoalLifecycle
from interview_growth.persistence.database import connect_database


def test_create_goal_is_idempotent_and_physically_isolated(
    goal_service_factory: Callable[[], GoalService],
    data_paths: DataPaths,
) -> None:
    service = goal_service_factory()

    first = service.create_goal(name="Agent Engineer", idempotency_key="create-agent")
    replay = service.create_goal(name="Agent Engineer", idempotency_key="create-agent")
    second = service.create_goal(name="LLM Infra", idempotency_key="create-infra")

    assert replay == first
    assert first.id != second.id
    assert data_paths.goal_database(first.id).is_file()
    assert data_paths.goal_database(second.id).is_file()
    assert data_paths.goal_database(first.id) != data_paths.goal_database(second.id)
    assert len(service.list_goals()) == 2

    with connect_database(data_paths.goal_database(first.id)) as connection:
        connection.execute(
            "INSERT INTO audit_log(event_type, payload_json, occurred_at) VALUES (?, ?, ?)",
            ("isolation_probe", "{}", "2026-07-19T10:10:00.000Z"),
        )
        connection.commit()
    with connect_database(data_paths.goal_database(second.id)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM audit_log WHERE event_type = 'isolation_probe'"
        ).fetchone()
    assert row is not None
    assert row["count"] == 0


def test_reusing_idempotency_key_with_different_input_fails(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    service = goal_service_factory()
    service.create_goal(name="Agent Engineer", idempotency_key="same-key")

    with pytest.raises(IdempotencyConflictError):
        service.create_goal(name="Different Role", idempotency_key="same-key")


def test_sessions_bind_to_exactly_one_current_goal(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    service = goal_service_factory()
    first = service.create_goal(name="Agent Engineer", idempotency_key="agent")
    second = service.create_goal(name="LLM Infra", idempotency_key="infra")

    with pytest.raises(NoCurrentGoalError):
        service.get_current_goal(session_id="session-a")

    service.select_goal(session_id="session-a", goal_id=first.id)
    service.select_goal(session_id="session-b", goal_id=second.id)
    assert service.get_current_goal(session_id="session-a") == first
    assert service.get_current_goal(session_id="session-b") == second

    service.select_goal(session_id="session-a", goal_id=second.id)
    assert service.get_current_goal(session_id="session-a") == second


def test_goal_lifecycle_enforces_confirmed_state_machine(
    goal_service_factory: Callable[[], GoalService],
    data_paths: DataPaths,
) -> None:
    service = goal_service_factory()
    goal = service.create_goal(name="Agent Engineer", idempotency_key="agent")
    service.select_goal(session_id="session-a", goal_id=goal.id)

    in_progress = service.change_current_goal_lifecycle(
        session_id="session-a",
        requested=GoalLifecycle.IN_PROGRESS,
    )
    paused = service.change_current_goal_lifecycle(
        session_id="session-a",
        requested=GoalLifecycle.PAUSED,
    )

    assert in_progress.lifecycle is GoalLifecycle.IN_PROGRESS
    assert paused.lifecycle is GoalLifecycle.PAUSED

    with connect_database(data_paths.goal_database(goal.id)) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM audit_log WHERE event_type = 'goal_lifecycle_changed'"
        ).fetchall()
    assert [json.loads(row["payload_json"])["to"] for row in rows] == [
        "in_progress",
        "paused",
    ]


def test_invalid_goal_lifecycle_transition_is_rejected(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    service = goal_service_factory()
    goal = service.create_goal(name="Agent Engineer", idempotency_key="agent")
    service.select_goal(session_id="session-a", goal_id=goal.id)

    with pytest.raises(InvalidLifecycleTransitionError):
        service.change_current_goal_lifecycle(
            session_id="session-a",
            requested=GoalLifecycle.ARCHIVED,
        )


def test_doctor_detects_registry_path_tampering(
    goal_service_factory: Callable[[], GoalService],
    data_paths: DataPaths,
) -> None:
    service = goal_service_factory()
    goal = service.create_goal(name="Agent Engineer", idempotency_key="agent")
    with sqlite3.connect(data_paths.registry_database) as connection:
        connection.execute(
            "UPDATE goals SET database_path = ? WHERE id = ?",
            (str(data_paths.root / "wrong.sqlite"), goal.id),
        )
        connection.commit()

    report = service.doctor()
    assert not report.ok
    assert report.goals_checked == 1
    assert any("outside its derived database path" in issue for issue in report.issues)
