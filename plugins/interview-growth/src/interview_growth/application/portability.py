"""Explicit goal backup, restore, export, import, and recoverable deletion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import Goal, GoalLifecycle
from interview_growth.domain.validation import new_id, request_hash, require_text
from interview_growth.persistence.database import connect_database
from interview_growth.persistence.goal_database import GoalDatabaseRepository
from interview_growth.persistence.migrations import initialize_goal_database
from interview_growth.persistence.registry import RegistryRepository

_PACKAGE_VERSION = 1
_MAX_DATABASE_BYTES = 512 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (
        sqlite3.connect(source) as source_connection,
        sqlite3.connect(destination) as destination_connection,
    ):
        source_connection.backup(destination_connection)
    os.chmod(destination, 0o600)


def _validate_database(path: Path, expected_goal_id: str | None = None) -> str:
    if not path.is_file() or path.stat().st_size > _MAX_DATABASE_BYTES:
        raise DomainValidationError("Goal database is missing or exceeds the import limit.")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            identity = connection.execute("SELECT id FROM goal_identity").fetchone()
    except sqlite3.Error as error:
        raise DomainValidationError(
            "Goal database is not a valid Interview Growth database."
        ) from error
    if integrity != ("ok",) or identity is None:
        raise DomainValidationError("Goal database failed its integrity or identity check.")
    goal_id = str(identity[0])
    if expected_goal_id is not None and goal_id != expected_goal_id:
        raise DomainValidationError("Backup belongs to a different goal.")
    return goal_id


class PortabilityService:
    def __init__(
        self,
        goals: GoalService,
        *,
        clock: Callable[[], str] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        self._goals = goals
        self._clock = clock
        self._id_factory = id_factory
        self._registry = RegistryRepository(goals.paths.registry_database)

    def backup(
        self,
        *,
        session_id: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        goal, source = self._goals.resolve_current_goal_database(session_id=session_id)
        clean_reason = require_text(reason, field="Backup reason", maximum=500)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=180)
        command_hash = request_hash({"goal_id": goal.id, "reason": clean_reason})
        existing = self._registry.find_operation(
            operation="goal_backup",
            idempotency_key=clean_key,
            request_hash=command_hash,
        )
        if existing is not None:
            return existing
        backup_id = self._id_factory()
        destination = self._backup_path(goal.id, backup_id)
        _copy_database(source, destination)
        _validate_database(destination, goal.id)
        checksum = _sha256(destination)
        timestamp = self._clock()
        backup = self._registry.record_backup(
            backup_id=backup_id,
            goal_id=goal.id,
            database_path=destination,
            sha256=checksum,
            reason=clean_reason,
            timestamp=timestamp,
        )
        response = {**backup, "verified": True}
        self._registry.record_operation(
            operation="goal_backup",
            idempotency_key=clean_key,
            request_hash=command_hash,
            response=response,
            timestamp=timestamp,
        )
        return response

    def list_backups(self, *, session_id: str) -> list[dict[str, Any]]:
        goal = self._goals.get_current_goal(session_id=session_id)
        return self._registry.list_backups(goal.id)

    def restore(
        self,
        *,
        session_id: str,
        backup_id: str,
        confirm_goal_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        goal, destination = self._goals.resolve_current_goal_database(session_id=session_id)
        if confirm_goal_id != goal.id:
            raise DomainValidationError("Restore confirmation must exactly match the goal ID.")
        if goal.lifecycle not in {
            GoalLifecycle.PAUSED,
            GoalLifecycle.ENDED,
            GoalLifecycle.ARCHIVED,
        }:
            raise DomainValidationError("Pause, end, or archive the goal before restoring it.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=160)
        command_hash = request_hash(
            {"goal_id": goal.id, "backup_id": backup_id, "confirm_goal_id": confirm_goal_id}
        )
        existing = self._registry.find_operation(
            operation="goal_restore",
            idempotency_key=clean_key,
            request_hash=command_hash,
        )
        if existing is not None:
            return existing
        backup = self._verified_backup(backup_id, goal.id)
        safety = self.backup(
            session_id=session_id,
            reason=f"Automatic safety backup before restoring {backup_id}",
            idempotency_key=f"{clean_key}:safety",
        )
        _copy_database(Path(str(backup["database_path"])), destination)
        initialize_goal_database(destination, goal.id, goal.created_at)
        if not GoalDatabaseRepository(destination, goal.id).verify_identity():
            raise RuntimeError("Restored database identity is invalid.")
        timestamp = self._clock()
        GoalDatabaseRepository(destination, goal.id).append_audit_event(
            event_type="goal_restored",
            payload={"backup_id": backup_id, "safety_backup_id": safety["id"]},
            occurred_at=timestamp,
        )
        response = {
            "goal_id": goal.id,
            "restored_backup_id": backup_id,
            "safety_backup_id": safety["id"],
            "restored_at": timestamp,
        }
        self._registry.record_operation(
            operation="goal_restore",
            idempotency_key=clean_key,
            request_hash=command_hash,
            response=response,
            timestamp=timestamp,
        )
        return response

    def export(
        self,
        *,
        session_id: str,
        output_path: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        goal, source = self._goals.resolve_current_goal_database(session_id=session_id)
        destination = Path(output_path).expanduser().resolve()
        if destination.suffix != ".igx":
            raise DomainValidationError("Export packages must use the .igx extension.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=180)
        command_hash = request_hash(
            {"goal_id": goal.id, "output_path": str(destination)}
        )
        existing = self._registry.find_operation(
            operation="goal_export",
            idempotency_key=clean_key,
            request_hash=command_hash,
        )
        if existing is not None:
            return existing
        if destination.exists():
            raise DomainValidationError("Export destination already exists; choose a new path.")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._goals.paths.root) as temporary:
            snapshot = Path(temporary) / "goal.sqlite"
            _copy_database(source, snapshot)
            checksum = _sha256(snapshot)
            counts = self._summary_counts(snapshot)
            manifest = {
                "package_version": _PACKAGE_VERSION,
                "exported_at": self._clock(),
                "goal": {
                    "id": goal.id,
                    "slug": goal.slug,
                    "name": goal.name,
                    "lifecycle": goal.lifecycle.value,
                },
                "goal_database_sha256": checksum,
                "counts": counts,
            }
            summary = self._summary_markdown(manifest)
            temporary_archive = Path(temporary) / "export.igx"
            with zipfile.ZipFile(
                temporary_archive, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.write(snapshot, "goal.sqlite")
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
                archive.writestr("summary.md", summary)
            shutil.move(temporary_archive, destination)
        os.chmod(destination, 0o600)
        timestamp = self._clock()
        response = {
            "goal_id": goal.id,
            "package_path": str(destination),
            "package_sha256": _sha256(destination),
            "manifest": manifest,
        }
        self._registry.record_operation(
            operation="goal_export",
            idempotency_key=clean_key,
            request_hash=command_hash,
            response=response,
            timestamp=timestamp,
        )
        return response

    def import_package(
        self,
        *,
        package_path: str,
        name: str | None,
        idempotency_key: str,
    ) -> Goal:
        package = Path(package_path).expanduser().resolve()
        if not package.is_file() or package.suffix != ".igx":
            raise DomainValidationError("Import requires an existing .igx package.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=150)
        package_checksum = _sha256(package)
        clean_name = None if name is None else require_text(name, field="Goal name", maximum=200)
        command_hash = request_hash(
            {"package_sha256": package_checksum, "name": clean_name}
        )
        existing = self._registry.find_operation(
            operation="goal_import",
            idempotency_key=clean_key,
            request_hash=command_hash,
        )
        if existing is not None:
            return self._registry.get_goal(str(existing["goal_id"]))
        with tempfile.TemporaryDirectory(dir=self._goals.paths.root) as temporary:
            source, manifest = self._extract_package(package, Path(temporary))
            original_goal_id = _validate_database(source)
            manifest_goal = cast(dict[str, Any], manifest["goal"])
            imported_name = clean_name or require_text(
                str(manifest_goal["name"]), field="Imported goal name", maximum=200
            )
            goal = self._goals.create_goal(
                name=imported_name,
                slug=None,
                idempotency_key=f"import:{clean_key}",
            )
            destination = self._goals.paths.goal_database(goal.id)
            _copy_database(source, destination)
            with connect_database(destination) as connection:
                connection.execute("UPDATE goal_identity SET id = ?", (goal.id,))
                connection.execute(
                    """
                    INSERT INTO audit_log(event_type, payload_json, occurred_at)
                    VALUES ('goal_imported', ?, ?)
                    """,
                    (
                        json.dumps(
                            {
                                "original_goal_id": original_goal_id,
                                "package_sha256": package_checksum,
                            },
                            separators=(",", ":"),
                        ),
                        self._clock(),
                    ),
                )
                connection.commit()
            initialize_goal_database(destination, goal.id, goal.created_at)
        timestamp = self._clock()
        self._registry.record_operation(
            operation="goal_import",
            idempotency_key=clean_key,
            request_hash=command_hash,
            response={"goal_id": goal.id},
            timestamp=timestamp,
        )
        return goal

    def delete_to_trash(
        self,
        *,
        session_id: str,
        backup_id: str,
        confirm_goal_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=180)
        command_hash = request_hash(
            {
                "goal_id": confirm_goal_id,
                "backup_id": backup_id,
                "confirm_goal_id": confirm_goal_id,
            }
        )
        existing = self._registry.find_operation(
            operation="goal_delete",
            idempotency_key=clean_key,
            request_hash=command_hash,
        )
        if existing is not None:
            return existing
        goal = self._goals.get_current_goal(session_id=session_id)
        if confirm_goal_id != goal.id:
            raise DomainValidationError("Delete confirmation must exactly match the goal ID.")
        if goal.lifecycle is not GoalLifecycle.ARCHIVED:
            raise DomainValidationError("Archive the goal before deleting it.")
        self._verified_backup(backup_id, goal.id)
        source = self._goals.paths.goal_directory(goal.id)
        trash = self._goals.paths.trash_directory / f"{goal.id}-{self._id_factory()}"
        if trash.exists():
            raise RuntimeError("Generated trash destination already exists.")
        shutil.move(source, trash)
        timestamp = self._clock()
        try:
            self._registry.mark_deleted(
                goal_id=goal.id, trash_path=trash, timestamp=timestamp
            )
        except Exception:
            shutil.move(trash, source)
            raise
        response = {
            "goal_id": goal.id,
            "backup_id": backup_id,
            "deleted_at": timestamp,
            "recoverable_trash_path": str(trash),
            "warning": (
                "The app registry no longer exposes this goal. The application trash and "
                "external or operating-system backups may still contain copies."
            ),
        }
        self._registry.record_operation(
            operation="goal_delete",
            idempotency_key=clean_key,
            request_hash=command_hash,
            response=response,
            timestamp=timestamp,
        )
        return response

    def _verified_backup(self, backup_id: str, goal_id: str) -> dict[str, Any]:
        backup = self._registry.get_backup(backup_id)
        if backup["goal_id"] != goal_id:
            raise DomainValidationError("Backup belongs to a different goal.")
        path = Path(str(backup["database_path"])).resolve()
        backup_root = self._goals.paths.backups_directory.resolve()
        if not path.is_relative_to(backup_root):
            raise RuntimeError("Registered backup path escaped the backup directory.")
        if _sha256(path) != backup["sha256"]:
            raise DomainValidationError("Backup checksum does not match the registry.")
        _validate_database(path, goal_id)
        return backup

    def _backup_path(self, goal_id: str, backup_id: str) -> Path:
        directory = self._goals.paths.backups_directory / goal_id
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory / f"{backup_id}.sqlite"

    @staticmethod
    def _extract_package(package: Path, directory: Path) -> tuple[Path, dict[str, Any]]:
        try:
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                if names != {"goal.sqlite", "manifest.json", "summary.md"}:
                    raise DomainValidationError("Export package has an unexpected file layout.")
                database_info = archive.getinfo("goal.sqlite")
                if database_info.file_size > _MAX_DATABASE_BYTES:
                    raise DomainValidationError("Imported goal database is too large.")
                manifest_raw = archive.read("manifest.json")
                database_raw = archive.read("goal.sqlite")
        except (zipfile.BadZipFile, KeyError) as error:
            raise DomainValidationError("Import package is corrupt.") from error
        try:
            manifest_value = json.loads(manifest_raw)
        except json.JSONDecodeError as error:
            raise DomainValidationError("Import manifest is invalid JSON.") from error
        if not isinstance(manifest_value, dict):
            raise DomainValidationError("Import manifest is invalid.")
        manifest = cast(dict[str, Any], manifest_value)
        if manifest.get("package_version") != _PACKAGE_VERSION:
            raise DomainValidationError("Unsupported export package version.")
        if not isinstance(manifest.get("goal"), dict):
            raise DomainValidationError("Import manifest goal metadata is invalid.")
        destination = directory / "goal.sqlite"
        destination.write_bytes(database_raw)
        if _sha256(destination) != manifest.get("goal_database_sha256"):
            raise DomainValidationError("Export package database checksum failed.")
        return destination, manifest

    @staticmethod
    def _summary_counts(database: Path) -> dict[str, int]:
        tables = {
            "questions": "questions",
            "interviews": "interview_sessions",
            "attempts": "attempts",
            "evaluations": "evaluations",
            "real_interviews": "real_interview_reviews",
        }
        with sqlite3.connect(database) as connection:
            available = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            return {
                label: (
                    int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    if table in available
                    else 0
                )
                for label, table in tables.items()
            }

    @staticmethod
    def _summary_markdown(manifest: dict[str, Any]) -> str:
        goal = cast(dict[str, Any], manifest["goal"])
        counts = cast(dict[str, int], manifest["counts"])
        return "\n".join(
            [
                f"# {goal['name']}",
                "",
                f"- Original goal ID: `{goal['id']}`",
                f"- Exported at: {manifest['exported_at']}",
                f"- Questions: {counts['questions']}",
                f"- Mock interviews: {counts['interviews']}",
                f"- Evaluations: {counts['evaluations']}",
                f"- Real interview reviews: {counts['real_interviews']}",
                "",
                "This package contains private interview data. Store it securely.",
            ]
        )
