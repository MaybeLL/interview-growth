from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from interview_growth.application.goals import GoalService
from interview_growth.application.portability import PortabilityService
from interview_growth.domain.errors import DomainValidationError, NoCurrentGoalError
from interview_growth.domain.models import GoalLifecycle
from interview_growth.persistence.database import connect_database
from interview_growth.persistence.goal_database import GoalDatabaseRepository


def _portability(goals: GoalService) -> PortabilityService:
    identifiers: Iterator[str] = iter(
        (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        )
    )
    return PortabilityService(
        goals,
        clock=lambda: "2026-07-20T12:00:00.000Z",
        id_factory=lambda: next(identifiers),
    )


def _create_selected_goal(factory: Callable[[], GoalService]) -> tuple[GoalService, str]:
    goals = factory()
    goal = goals.create_goal(name="Agent Engineer", idempotency_key="create-portable")
    goals.select_goal(session_id="session-a", goal_id=goal.id)
    return goals, goal.id


def test_verified_backup_and_restore_create_a_safety_backup(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, goal_id = _create_selected_goal(goal_service_factory)
    goals.change_current_goal_lifecycle(
        session_id="session-a", requested=GoalLifecycle.IN_PROGRESS
    )
    goals.change_current_goal_lifecycle(
        session_id="session-a", requested=GoalLifecycle.PAUSED
    )
    database = goals.paths.goal_database(goal_id)
    repository = GoalDatabaseRepository(database, goal_id)
    repository.append_audit_event(
        event_type="before_backup", payload={}, occurred_at="2026-07-20T10:00:00.000Z"
    )
    portability = _portability(goals)
    backup = portability.backup(
        session_id="session-a",
        reason="Before changing training data",
        idempotency_key="backup-before-change",
    )
    assert backup["verified"] is True
    assert portability.backup(
        session_id="session-a",
        reason="Before changing training data",
        idempotency_key="backup-before-change",
    ) == backup
    repository.append_audit_event(
        event_type="after_backup", payload={}, occurred_at="2026-07-20T11:00:00.000Z"
    )

    restored = portability.restore(
        session_id="session-a",
        backup_id=str(backup["id"]),
        confirm_goal_id=goal_id,
        idempotency_key="restore-before-change",
    )
    assert restored["restored_backup_id"] == backup["id"]
    assert restored["safety_backup_id"] != backup["id"]
    assert len(portability.list_backups(session_id="session-a")) == 2
    with connect_database(database) as connection:
        events = {
            str(row["event_type"])
            for row in connection.execute("SELECT event_type FROM audit_log").fetchall()
        }
    assert "before_backup" in events
    assert "after_backup" not in events
    assert "goal_restored" in events


def test_export_import_creates_a_new_isolated_goal(
    goal_service_factory: Callable[[], GoalService], tmp_path: Path
) -> None:
    goals, original_goal_id = _create_selected_goal(goal_service_factory)
    GoalDatabaseRepository(
        goals.paths.goal_database(original_goal_id), original_goal_id
    ).append_audit_event(
        event_type="portable_marker",
        payload={"private": "retained"},
        occurred_at="2026-07-20T10:00:00.000Z",
    )
    portability = _portability(goals)
    package = tmp_path / "agent-engineer.igx"
    exported = portability.export(
        session_id="session-a",
        output_path=str(package),
        idempotency_key="export-agent",
    )
    assert package.is_file()
    assert exported["package_path"] == str(package)

    imported = portability.import_package(
        package_path=str(package),
        name="Imported Agent Engineer",
        idempotency_key="import-agent",
    )
    assert imported.id != original_goal_id
    assert goals.paths.goal_database(imported.id) != goals.paths.goal_database(original_goal_id)
    assert GoalDatabaseRepository(
        goals.paths.goal_database(imported.id), imported.id
    ).verify_identity()
    with connect_database(goals.paths.goal_database(imported.id)) as connection:
        events = {
            str(row["event_type"])
            for row in connection.execute("SELECT event_type FROM audit_log").fetchall()
        }
    assert {"portable_marker", "goal_imported"} <= events
    assert portability.import_package(
        package_path=str(package),
        name="Imported Agent Engineer",
        idempotency_key="import-agent",
    ).id == imported.id


def test_delete_requires_archive_backup_and_exact_confirmation(
    goal_service_factory: Callable[[], GoalService],
) -> None:
    goals, goal_id = _create_selected_goal(goal_service_factory)
    portability = _portability(goals)
    backup = portability.backup(
        session_id="session-a",
        reason="Required deletion backup",
        idempotency_key="delete-backup",
    )
    goals.change_current_goal_lifecycle(
        session_id="session-a", requested=GoalLifecycle.IN_PROGRESS
    )
    goals.change_current_goal_lifecycle(
        session_id="session-a", requested=GoalLifecycle.ENDED
    )
    goals.change_current_goal_lifecycle(
        session_id="session-a", requested=GoalLifecycle.ARCHIVED
    )
    with pytest.raises(DomainValidationError):
        portability.delete_to_trash(
            session_id="session-a",
            backup_id=str(backup["id"]),
            confirm_goal_id="wrong-id",
            idempotency_key="bad-delete",
        )
    deleted = portability.delete_to_trash(
        session_id="session-a",
        backup_id=str(backup["id"]),
        confirm_goal_id=goal_id,
        idempotency_key="delete-goal",
    )
    assert Path(str(deleted["recoverable_trash_path"])).is_dir()
    assert not goals.paths.goal_directory(goal_id).exists()
    assert portability.delete_to_trash(
        session_id="session-a",
        backup_id=str(backup["id"]),
        confirm_goal_id=goal_id,
        idempotency_key="delete-goal",
    ) == deleted
    assert all(goal.id != goal_id for goal in goals.list_goals())
    with pytest.raises(NoCurrentGoalError):
        goals.get_current_goal(session_id="session-a")
