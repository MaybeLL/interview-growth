"""Goal management use cases."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from interview_growth.config import DataPaths
from interview_growth.domain.errors import DomainValidationError, NoCurrentGoalError
from interview_growth.domain.models import Goal, GoalLifecycle, require_lifecycle_transition
from interview_growth.persistence.goal_database import GoalDatabaseRepository
from interview_growth.persistence.migrations import (
    initialize_goal_database,
    initialize_registry_database,
)
from interview_growth.persistence.registry import RegistryRepository


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uuid4() -> str:
    return str(uuid.uuid4())


def _request_hash(payload: dict[str, str | None]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _normalized_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug[:48] or "goal"


def _require_text(value: str, *, field: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError(f"{field} must not be empty.")
    if len(normalized) > maximum:
        raise DomainValidationError(f"{field} must be at most {maximum} characters.")
    return normalized


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok: bool
    goals_checked: int
    issues: tuple[str, ...]


class GoalService:
    """Coordinate registry operations with physically isolated goal databases."""

    def __init__(
        self,
        paths: DataPaths,
        *,
        clock: Callable[[], str] = utc_now,
        id_factory: Callable[[], str] = _uuid4,
    ) -> None:
        self.paths = paths
        self._clock = clock
        self._id_factory = id_factory
        self.paths.ensure_layout()
        initialize_registry_database(self.paths.registry_database)
        self._registry = RegistryRepository(self.paths.registry_database)

    def create_goal(
        self,
        *,
        name: str,
        idempotency_key: str,
        slug: str | None = None,
    ) -> Goal:
        clean_name = _require_text(name, field="Goal name", maximum=200)
        clean_key = _require_text(idempotency_key, field="Idempotency key", maximum=200)
        clean_slug = None if slug is None else _require_text(slug, field="Goal slug", maximum=64)
        request_hash = _request_hash({"name": clean_name, "slug": clean_slug})
        existing = self._registry.find_idempotent_goal(
            idempotency_key=clean_key,
            request_hash=request_hash,
        )
        if existing is not None:
            return existing

        goal_id = self._id_factory().lower()
        timestamp = self._clock()
        base_slug = _normalized_slug(clean_slug or clean_name)
        goal = Goal(
            id=goal_id,
            slug=f"{base_slug}-{goal_id[:8]}",
            name=clean_name,
            lifecycle=GoalLifecycle.CONFIGURING,
            created_at=timestamp,
            updated_at=timestamp,
        )
        database_path = self.paths.goal_database(goal.id)
        if database_path.exists():
            raise RuntimeError("Generated goal database path already exists.")

        try:
            initialize_goal_database(database_path, goal.id, timestamp)
            self._registry.insert_goal(
                goal=goal,
                database_path=database_path,
                idempotency_key=clean_key,
                request_hash=request_hash,
            )
        except (OSError, sqlite3.Error):
            self._clean_failed_goal_directory(database_path.parent)
            raise
        return goal

    def list_goals(self) -> tuple[Goal, ...]:
        return self._registry.list_goals()

    def select_goal(self, *, session_id: str, goal_id: str) -> Goal:
        clean_session_id = _require_text(session_id, field="Session ID", maximum=200)
        goal = self._registry.bind_session(
            session_id=clean_session_id,
            goal_id=goal_id,
            timestamp=self._clock(),
        )
        database_path = self._registry.get_goal_database_path(goal.id)
        if not GoalDatabaseRepository(database_path, goal.id).verify_identity():
            raise RuntimeError("The selected goal database is missing or has the wrong identity.")
        return goal

    def get_current_goal(self, *, session_id: str) -> Goal:
        clean_session_id = _require_text(session_id, field="Session ID", maximum=200)
        goal = self._registry.get_bound_goal(clean_session_id)
        if goal is None:
            raise NoCurrentGoalError(
                "This session has no current growth goal. Select a goal explicitly first."
            )
        return goal

    def resolve_current_goal_database(self, *, session_id: str) -> tuple[Goal, Path]:
        """Resolve and migrate storage for the explicitly selected goal."""

        goal = self.get_current_goal(session_id=session_id)
        registered_path = self._registry.get_goal_database_path(goal.id).resolve()
        expected_path = self.paths.goal_database(goal.id).resolve()
        if registered_path != expected_path:
            raise RuntimeError("The current goal points outside its derived database path.")
        initialize_goal_database(registered_path, goal.id, goal.created_at)
        if not GoalDatabaseRepository(registered_path, goal.id).verify_identity():
            raise RuntimeError("The current goal database has the wrong identity.")
        return goal, registered_path

    def change_current_goal_lifecycle(
        self,
        *,
        session_id: str,
        requested: GoalLifecycle,
    ) -> Goal:
        current = self.get_current_goal(session_id=session_id)
        require_lifecycle_transition(current.lifecycle, requested)
        if current.lifecycle == requested:
            return current
        timestamp = self._clock()
        updated = self._registry.update_lifecycle(
            goal_id=current.id,
            expected=current.lifecycle,
            requested=requested,
            timestamp=timestamp,
        )
        goal_repository = GoalDatabaseRepository(
            self._registry.get_goal_database_path(updated.id),
            updated.id,
        )
        goal_repository.append_audit_event(
            event_type="goal_lifecycle_changed",
            payload={"from": current.lifecycle.value, "to": requested.value},
            occurred_at=timestamp,
        )
        return updated

    def doctor(self) -> DoctorReport:
        issues: list[str] = []
        goals = self.list_goals()
        registered_directories: set[Path] = set()
        for goal in goals:
            expected_path = self.paths.goal_database(goal.id)
            registered_path = self._registry.get_goal_database_path(goal.id).resolve()
            registered_directories.add(registered_path.parent)
            if registered_path != expected_path.resolve():
                issues.append(f"Goal {goal.id} points outside its derived database path.")
                continue
            if not GoalDatabaseRepository(registered_path, goal.id).verify_identity():
                issues.append(f"Goal {goal.id} database is missing or has a mismatched identity.")

        if self.paths.goals_directory.exists():
            for directory in self.paths.goals_directory.iterdir():
                if directory.is_dir() and directory.resolve() not in registered_directories:
                    issues.append(f"Unregistered goal directory: {directory.name}")
        return DoctorReport(ok=not issues, goals_checked=len(goals), issues=tuple(issues))

    @staticmethod
    def _clean_failed_goal_directory(directory: Path) -> None:
        if directory.is_dir():
            shutil.rmtree(directory)
