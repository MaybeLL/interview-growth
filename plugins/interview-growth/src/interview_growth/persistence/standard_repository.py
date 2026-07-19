"""Persistence for target-role sources, topics, capabilities, and standards."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import (
    CapabilityDimension,
    Requirement,
    RequirementInput,
    SourceMaterial,
    SourceMaterialKind,
    StandardDraft,
    StandardVersion,
    Topic,
)

from .scoped import GoalScopedStore, json_object


def _aliases(connection: sqlite3.Connection, topic_id: str) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT alias FROM topic_aliases WHERE topic_id = ? ORDER BY normalized_alias",
        (topic_id,),
    ).fetchall()
    return tuple(row["alias"] for row in rows)


def _topic(connection: sqlite3.Connection, row: sqlite3.Row) -> Topic:
    return Topic(
        id=row["id"],
        canonical_name=row["canonical_name"],
        description=row["description"],
        parent_id=row["parent_id"],
        aliases=_aliases(connection, row["id"]),
        status=row["status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _capability(row: sqlite3.Row) -> CapabilityDimension:
    return CapabilityDimension(
        id=row["id"],
        canonical_name=row["canonical_name"],
        description=row["description"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class StandardRepository:
    def __init__(self, database_path: Path, goal_id: str) -> None:
        self._store = GoalScopedStore(database_path, goal_id)

    def create_source(
        self,
        *,
        material: SourceMaterial,
        idempotency_key: str,
        request_hash: str,
    ) -> SourceMaterial:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO source_materials(id, kind, title, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    material.id,
                    material.kind.value,
                    material.title,
                    material.content,
                    material.created_at,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="source_material_added",
                payload={"source_id": material.id, "kind": material.kind.value},
                timestamp=material.created_at,
            )
            return {"source_id": material.id}

        response = self._store.write_idempotent(
            operation_name="source_material_add",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=material.created_at,
            operation=write,
        )
        return self.get_source(str(response["source_id"]))

    def get_source(self, source_id: str) -> SourceMaterial:
        def read(connection: sqlite3.Connection) -> SourceMaterial:
            row = connection.execute(
                "SELECT id, kind, title, content, created_at FROM source_materials WHERE id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown source material ID: {source_id}")
            return SourceMaterial(
                id=row["id"],
                kind=SourceMaterialKind(row["kind"]),
                title=row["title"],
                content=row["content"],
                created_at=row["created_at"],
            )

        return self._store.read(read)

    def create_topic(
        self,
        *,
        topic: Topic,
        normalized_name: str,
        normalized_aliases: tuple[tuple[str, str], ...],
        idempotency_key: str,
        request_hash: str,
    ) -> Topic:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            if topic.parent_id is not None:
                parent = connection.execute(
                    "SELECT status FROM topics WHERE id = ?", (topic.parent_id,)
                ).fetchone()
                if parent is None or parent["status"] != "active":
                    raise DomainValidationError("Topic parent must be an active topic.")
            connection.execute(
                """
                INSERT INTO topics(
                    id, parent_id, canonical_name, normalized_name, description,
                    status, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?)
                """,
                (
                    topic.id,
                    topic.parent_id,
                    topic.canonical_name,
                    normalized_name,
                    topic.description,
                    topic.created_at,
                    topic.updated_at,
                ),
            )
            connection.executemany(
                "INSERT INTO topic_aliases(topic_id, alias, normalized_alias) VALUES (?, ?, ?)",
                ((topic.id, alias, normalized) for alias, normalized in normalized_aliases),
            )
            self._store.append_audit(
                connection,
                event_type="topic_created",
                payload={"topic_id": topic.id},
                timestamp=topic.created_at,
            )
            return {"topic_id": topic.id}

        response = self._store.write_idempotent(
            operation_name="topic_create",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=topic.created_at,
            operation=write,
        )
        return self.get_topic(str(response["topic_id"]))

    def get_topic(self, topic_id: str) -> Topic:
        def read(connection: sqlite3.Connection) -> Topic:
            row = connection.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown topic ID: {topic_id}")
            return _topic(connection, row)

        return self._store.read(read)

    def list_topics(self, *, active_only: bool = True) -> tuple[Topic, ...]:
        def read(connection: sqlite3.Connection) -> tuple[Topic, ...]:
            sql = "SELECT * FROM topics"
            if active_only:
                sql += " WHERE status = 'active'"
            sql += " ORDER BY normalized_name, id"
            return tuple(_topic(connection, row) for row in connection.execute(sql).fetchall())

        return self._store.read(read)

    def create_capability(
        self,
        *,
        capability: CapabilityDimension,
        normalized_name: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CapabilityDimension:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO capability_dimensions(
                    id, canonical_name, normalized_name, description,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    capability.id,
                    capability.canonical_name,
                    normalized_name,
                    capability.description,
                    capability.created_at,
                    capability.updated_at,
                ),
            )
            self._store.append_audit(
                connection,
                event_type="capability_created",
                payload={"capability_id": capability.id},
                timestamp=capability.created_at,
            )
            return {"capability_id": capability.id}

        response = self._store.write_idempotent(
            operation_name="capability_create",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=capability.created_at,
            operation=write,
        )
        return self.get_capability(str(response["capability_id"]))

    def get_capability(self, capability_id: str) -> CapabilityDimension:
        def read(connection: sqlite3.Connection) -> CapabilityDimension:
            row = connection.execute(
                "SELECT * FROM capability_dimensions WHERE id = ?", (capability_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown capability ID: {capability_id}")
            return _capability(row)

        return self._store.read(read)

    def list_capabilities(self) -> tuple[CapabilityDimension, ...]:
        return self._store.read(
            lambda connection: tuple(
                _capability(row)
                for row in connection.execute(
                    "SELECT * FROM capability_dimensions ORDER BY normalized_name, id"
                ).fetchall()
            )
        )

    def create_draft(
        self,
        *,
        draft: StandardDraft,
        topic_requirements: tuple[RequirementInput, ...],
        capability_requirements: tuple[RequirementInput, ...],
        idempotency_key: str,
        request_hash: str,
    ) -> StandardDraft:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO standard_drafts(
                    id, revision, status, role_profile_json, created_at, updated_at
                ) VALUES (?, 1, 'draft', ?, ?, ?)
                """,
                (
                    draft.id,
                    json.dumps(draft.role_profile, ensure_ascii=False, separators=(",", ":")),
                    draft.created_at,
                    draft.updated_at,
                ),
            )
            connection.executemany(
                "INSERT INTO standard_draft_sources(draft_id, source_id) VALUES (?, ?)",
                ((draft.id, source_id) for source_id in draft.source_ids),
            )
            connection.executemany(
                """
                INSERT INTO standard_draft_topic_requirements(
                    draft_id, topic_id, required_level, weight, critical,
                    minimum_evidence_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        draft.id,
                        item.subject_id,
                        item.required_level,
                        item.weight,
                        int(item.critical),
                        item.minimum_evidence_count,
                    )
                    for item in topic_requirements
                ),
            )
            connection.executemany(
                """
                INSERT INTO standard_draft_capability_requirements(
                    draft_id, capability_id, required_level, weight, critical,
                    minimum_evidence_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        draft.id,
                        item.subject_id,
                        item.required_level,
                        item.weight,
                        int(item.critical),
                        item.minimum_evidence_count,
                    )
                    for item in capability_requirements
                ),
            )
            self._store.append_audit(
                connection,
                event_type="standard_draft_created",
                payload={"draft_id": draft.id, "revision": 1},
                timestamp=draft.created_at,
            )
            return {"draft_id": draft.id}

        response = self._store.write_idempotent(
            operation_name="standard_create_draft",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=draft.created_at,
            operation=write,
        )
        return self.get_draft(str(response["draft_id"]))

    def get_draft(self, draft_id: str) -> StandardDraft:
        def read(connection: sqlite3.Connection) -> StandardDraft:
            row = connection.execute(
                "SELECT * FROM standard_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown standard draft ID: {draft_id}")
            sources = connection.execute(
                """
                SELECT source_id FROM standard_draft_sources
                WHERE draft_id = ? ORDER BY source_id
                """,
                (draft_id,),
            ).fetchall()
            return StandardDraft(
                id=row["id"],
                revision=row["revision"],
                status=row["status"],
                role_profile=json_object(row["role_profile_json"]),
                source_ids=tuple(item["source_id"] for item in sources),
                topic_requirements=self._draft_requirements(connection, draft_id, topic=True),
                capability_requirements=self._draft_requirements(
                    connection, draft_id, topic=False
                ),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        return self._store.read(read)

    def approve_draft(
        self,
        *,
        standard_id: str,
        draft_id: str,
        expected_revision: int,
        timestamp: str,
        idempotency_key: str,
        request_hash: str,
    ) -> StandardVersion:
        def write(connection: sqlite3.Connection) -> dict[str, Any]:
            draft = connection.execute(
                "SELECT * FROM standard_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if draft is None:
                raise DomainValidationError(f"Unknown standard draft ID: {draft_id}")
            if draft["revision"] != expected_revision:
                raise DomainValidationError("Standard draft revision changed; reload and retry.")
            if draft["status"] != "draft":
                raise DomainValidationError("Only an unapproved draft can be approved.")
            next_version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 AS value FROM standard_versions"
                ).fetchone()["value"]
            )
            connection.execute(
                """
                INSERT INTO standard_versions(
                    id, version_number, source_draft_id, source_draft_revision,
                    role_profile_json, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    standard_id,
                    next_version,
                    draft_id,
                    expected_revision,
                    draft["role_profile_json"],
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO standard_version_sources(standard_version_id, source_id)
                SELECT ?, source_id FROM standard_draft_sources WHERE draft_id = ?
                """,
                (standard_id, draft_id),
            )
            connection.execute(
                """
                INSERT INTO standard_topic_requirements(
                    standard_version_id, topic_id, topic_name_snapshot, required_level,
                    weight, critical, minimum_evidence_count
                )
                SELECT ?, requirement.topic_id, topic.canonical_name,
                       requirement.required_level, requirement.weight,
                       requirement.critical, requirement.minimum_evidence_count
                FROM standard_draft_topic_requirements AS requirement
                JOIN topics AS topic ON topic.id = requirement.topic_id
                WHERE requirement.draft_id = ?
                """,
                (standard_id, draft_id),
            )
            connection.execute(
                """
                INSERT INTO standard_capability_requirements(
                    standard_version_id, capability_id, capability_name_snapshot,
                    required_level, weight, critical, minimum_evidence_count
                )
                SELECT ?, requirement.capability_id, capability.canonical_name,
                       requirement.required_level, requirement.weight,
                       requirement.critical, requirement.minimum_evidence_count
                FROM standard_draft_capability_requirements AS requirement
                JOIN capability_dimensions AS capability
                    ON capability.id = requirement.capability_id
                WHERE requirement.draft_id = ?
                """,
                (standard_id, draft_id),
            )
            connection.execute(
                "UPDATE standard_drafts SET status = 'approved', updated_at = ? WHERE id = ?",
                (timestamp, draft_id),
            )
            self._store.append_audit(
                connection,
                event_type="standard_approved",
                payload={
                    "standard_version_id": standard_id,
                    "version_number": next_version,
                    "draft_id": draft_id,
                },
                timestamp=timestamp,
            )
            return {"standard_version_id": standard_id}

        response = self._store.write_idempotent(
            operation_name="standard_approve",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            timestamp=timestamp,
            operation=write,
        )
        return self.get_version(str(response["standard_version_id"]))

    def get_version(self, standard_id: str) -> StandardVersion:
        def read(connection: sqlite3.Connection) -> StandardVersion:
            row = connection.execute(
                "SELECT * FROM standard_versions WHERE id = ?", (standard_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError(f"Unknown standard version ID: {standard_id}")
            sources = connection.execute(
                """
                SELECT source_id FROM standard_version_sources
                WHERE standard_version_id = ? ORDER BY source_id
                """,
                (standard_id,),
            ).fetchall()
            return StandardVersion(
                id=row["id"],
                version_number=row["version_number"],
                source_draft_id=row["source_draft_id"],
                source_draft_revision=row["source_draft_revision"],
                role_profile=json_object(row["role_profile_json"]),
                source_ids=tuple(item["source_id"] for item in sources),
                topic_requirements=self._version_requirements(
                    connection, standard_id, topic=True
                ),
                capability_requirements=self._version_requirements(
                    connection, standard_id, topic=False
                ),
                approved_at=row["approved_at"],
            )

        return self._store.read(read)

    def list_versions(self) -> tuple[StandardVersion, ...]:
        identifiers = self._store.read(
            lambda connection: tuple(
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM standard_versions ORDER BY version_number"
                ).fetchall()
            )
        )
        return tuple(self.get_version(identifier) for identifier in identifiers)

    def current_version(self) -> StandardVersion | None:
        identifier = self._store.read(
            lambda connection: (
                lambda row: None if row is None else str(row["id"])
            )(
                connection.execute(
                    "SELECT id FROM standard_versions ORDER BY version_number DESC LIMIT 1"
                ).fetchone()
            )
        )
        return None if identifier is None else self.get_version(identifier)

    @staticmethod
    def _draft_requirements(
        connection: sqlite3.Connection,
        draft_id: str,
        *,
        topic: bool,
    ) -> tuple[Requirement, ...]:
        if topic:
            subject_column, table, subject_table = "topic_id", "topic", "topics"
        else:
            subject_column, table, subject_table = (
                "capability_id",
                "capability",
                "capability_dimensions",
            )
        rows = connection.execute(
            f"""
            SELECT requirement.{subject_column} AS subject_id,
                   subject.canonical_name AS subject_name,
                   requirement.required_level, requirement.weight,
                   requirement.critical, requirement.minimum_evidence_count
            FROM standard_draft_{table}_requirements AS requirement
            JOIN {subject_table} AS subject ON subject.id = requirement.{subject_column}
            WHERE requirement.draft_id = ? ORDER BY subject.normalized_name
            """,
            (draft_id,),
        ).fetchall()
        return tuple(
            Requirement(
                subject_id=row["subject_id"],
                subject_name=row["subject_name"],
                required_level=row["required_level"],
                weight=row["weight"],
                critical=bool(row["critical"]),
                minimum_evidence_count=row["minimum_evidence_count"],
            )
            for row in rows
        )

    @staticmethod
    def _version_requirements(
        connection: sqlite3.Connection,
        standard_id: str,
        *,
        topic: bool,
    ) -> tuple[Requirement, ...]:
        if topic:
            table, subject_id, subject_name = (
                "standard_topic_requirements",
                "topic_id",
                "topic_name_snapshot",
            )
        else:
            table, subject_id, subject_name = (
                "standard_capability_requirements",
                "capability_id",
                "capability_name_snapshot",
            )
        rows = connection.execute(
            f"""
            SELECT {subject_id} AS subject_id, {subject_name} AS subject_name,
                   required_level, weight, critical, minimum_evidence_count
            FROM {table} WHERE standard_version_id = ? ORDER BY subject_name
            """,
            (standard_id,),
        ).fetchall()
        return tuple(
            Requirement(
                subject_id=row["subject_id"],
                subject_name=row["subject_name"],
                required_level=row["required_level"],
                weight=row["weight"],
                critical=bool(row["critical"]),
                minimum_evidence_count=row["minimum_evidence_count"],
            )
            for row in rows
        )
