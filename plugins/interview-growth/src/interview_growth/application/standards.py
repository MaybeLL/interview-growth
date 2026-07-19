"""Target-role standards and taxonomy use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import (
    CapabilityDimension,
    RequirementInput,
    SourceMaterial,
    SourceMaterialKind,
    StandardDraft,
    StandardVersion,
    Topic,
)
from interview_growth.domain.validation import (
    new_id,
    normalize_name,
    request_hash,
    require_evidence_count,
    require_level,
    require_text,
    require_weight,
)
from interview_growth.persistence.standard_repository import StandardRepository


@dataclass(frozen=True, slots=True)
class DuplicateSuggestion:
    id: str
    canonical_name: str
    score: float
    matched_by: str


class StandardService:
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

    def add_source_material(
        self,
        *,
        session_id: str,
        kind: SourceMaterialKind,
        title: str,
        content: str,
        idempotency_key: str,
    ) -> SourceMaterial:
        clean_title = require_text(title, field="Source title", maximum=300)
        clean_content = require_text(content, field="Source content", maximum=100_000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        material = SourceMaterial(
            id=self._id_factory(),
            kind=kind,
            title=clean_title,
            content=clean_content,
            created_at=self._clock(),
        )
        repository = self._repository(session_id)
        return repository.create_source(
            material=material,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {"kind": kind.value, "title": clean_title, "content": clean_content}
            ),
        )

    def create_topic(
        self,
        *,
        session_id: str,
        canonical_name: str,
        description: str,
        parent_id: str | None,
        aliases: Sequence[str],
        idempotency_key: str,
    ) -> Topic:
        clean_name = require_text(canonical_name, field="Topic name", maximum=120)
        clean_description = " ".join(description.split())
        if len(clean_description) > 1000:
            raise DomainValidationError("Topic description must be at most 1000 characters.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        normalized_name = normalize_name(clean_name)
        alias_pairs: list[tuple[str, str]] = []
        seen = {normalized_name}
        for alias in aliases:
            clean_alias = require_text(alias, field="Topic alias", maximum=120)
            normalized_alias = normalize_name(clean_alias)
            if normalized_alias in seen:
                continue
            seen.add(normalized_alias)
            alias_pairs.append((clean_alias, normalized_alias))

        repository = self._repository(session_id)
        exact = [
            item
            for item in self._suggest_topic_duplicates(repository, clean_name, limit=10)
            if item.score == 1.0
        ]
        if exact:
            raise DomainValidationError(
                f"Topic name or alias already exists on topic {exact[0].id}."
            )
        timestamp = self._clock()
        topic = Topic(
            id=self._id_factory(),
            canonical_name=clean_name,
            description=clean_description,
            parent_id=parent_id,
            aliases=tuple(alias for alias, _ in alias_pairs),
            status="active",
            version=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return repository.create_topic(
            topic=topic,
            normalized_name=normalized_name,
            normalized_aliases=tuple(alias_pairs),
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "canonical_name": clean_name,
                    "description": clean_description,
                    "parent_id": parent_id,
                    "aliases": sorted(alias for alias, _ in alias_pairs),
                }
            ),
        )

    def list_topics(self, *, session_id: str, active_only: bool = True) -> tuple[Topic, ...]:
        return self._repository(session_id).list_topics(active_only=active_only)

    def suggest_topic_duplicates(
        self,
        *,
        session_id: str,
        name: str,
        limit: int = 5,
    ) -> tuple[DuplicateSuggestion, ...]:
        if limit < 1 or limit > 20:
            raise DomainValidationError("Duplicate suggestion limit must be between 1 and 20.")
        clean_name = require_text(name, field="Topic name", maximum=120)
        return self._suggest_topic_duplicates(
            self._repository(session_id), clean_name, limit=limit
        )

    def create_capability(
        self,
        *,
        session_id: str,
        canonical_name: str,
        description: str,
        idempotency_key: str,
    ) -> CapabilityDimension:
        clean_name = require_text(canonical_name, field="Capability name", maximum=120)
        clean_description = " ".join(description.split())
        if len(clean_description) > 1000:
            raise DomainValidationError("Capability description must be at most 1000 characters.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        repository = self._repository(session_id)
        normalized = normalize_name(clean_name)
        if any(
            normalize_name(item.canonical_name) == normalized
            for item in repository.list_capabilities()
        ):
            raise DomainValidationError("A capability with this canonical name already exists.")
        timestamp = self._clock()
        capability = CapabilityDimension(
            id=self._id_factory(),
            canonical_name=clean_name,
            description=clean_description,
            version=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return repository.create_capability(
            capability=capability,
            normalized_name=normalized,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {"canonical_name": clean_name, "description": clean_description}
            ),
        )

    def list_capabilities(self, *, session_id: str) -> tuple[CapabilityDimension, ...]:
        return self._repository(session_id).list_capabilities()

    def create_draft(
        self,
        *,
        session_id: str,
        role_profile: Mapping[str, Any],
        source_ids: Sequence[str],
        topic_requirements: Sequence[RequirementInput],
        capability_requirements: Sequence[RequirementInput],
        idempotency_key: str,
    ) -> StandardDraft:
        profile = dict(role_profile)
        self._validate_role_profile(profile)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        clean_sources = tuple(dict.fromkeys(source_ids))
        clean_topics = self._validate_requirements(topic_requirements, kind="topic")
        clean_capabilities = self._validate_requirements(
            capability_requirements, kind="capability"
        )
        if not clean_topics or not clean_capabilities:
            raise DomainValidationError(
                "A standard draft requires at least one topic and one capability requirement."
            )
        repository = self._repository(session_id)
        for source_id in clean_sources:
            repository.get_source(source_id)
        active_topics = {item.id for item in repository.list_topics()}
        if any(item.subject_id not in active_topics for item in clean_topics):
            raise DomainValidationError("A topic requirement references an unknown active topic.")
        capabilities = {item.id for item in repository.list_capabilities()}
        if any(item.subject_id not in capabilities for item in clean_capabilities):
            raise DomainValidationError(
                "A capability requirement references an unknown capability."
            )
        timestamp = self._clock()
        draft = StandardDraft(
            id=self._id_factory(),
            revision=1,
            status="draft",
            role_profile=profile,
            source_ids=clean_sources,
            topic_requirements=(),
            capability_requirements=(),
            created_at=timestamp,
            updated_at=timestamp,
        )
        return repository.create_draft(
            draft=draft,
            topic_requirements=clean_topics,
            capability_requirements=clean_capabilities,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "role_profile": profile,
                    "source_ids": sorted(clean_sources),
                    "topic_requirements": [
                        self._requirement_payload(item) for item in clean_topics
                    ],
                    "capability_requirements": [
                        self._requirement_payload(item) for item in clean_capabilities
                    ],
                }
            ),
        )

    def get_draft(self, *, session_id: str, draft_id: str) -> StandardDraft:
        return self._repository(session_id).get_draft(draft_id)

    def approve_draft(
        self,
        *,
        session_id: str,
        draft_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> StandardVersion:
        if expected_revision < 1:
            raise DomainValidationError("Expected draft revision must be positive.")
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        return self._repository(session_id).approve_draft(
            standard_id=self._id_factory(),
            draft_id=draft_id,
            expected_revision=expected_revision,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {"draft_id": draft_id, "expected_revision": expected_revision}
            ),
        )

    def list_versions(self, *, session_id: str) -> tuple[StandardVersion, ...]:
        return self._repository(session_id).list_versions()

    def current_version(self, *, session_id: str) -> StandardVersion | None:
        return self._repository(session_id).current_version()

    def compare_versions(
        self,
        *,
        session_id: str,
        older_id: str,
        newer_id: str,
    ) -> dict[str, Any]:
        repository = self._repository(session_id)
        older = repository.get_version(older_id)
        newer = repository.get_version(newer_id)
        return {
            "older_version": older.version_number,
            "newer_version": newer.version_number,
            "role_profile_changed": older.role_profile != newer.role_profile,
            "topic_requirements": self._requirement_diff(
                older.topic_requirements, newer.topic_requirements
            ),
            "capability_requirements": self._requirement_diff(
                older.capability_requirements, newer.capability_requirements
            ),
        }

    def _repository(self, session_id: str) -> StandardRepository:
        goal, database_path = self._goals.resolve_current_goal_database(session_id=session_id)
        return StandardRepository(database_path, goal.id)

    @staticmethod
    def _suggest_topic_duplicates(
        repository: StandardRepository,
        name: str,
        *,
        limit: int,
    ) -> tuple[DuplicateSuggestion, ...]:
        normalized = normalize_name(name)
        suggestions: list[DuplicateSuggestion] = []
        for topic in repository.list_topics(active_only=True):
            candidates = (
                (topic.canonical_name, "canonical_name"),
                *((alias, "alias") for alias in topic.aliases),
            )
            best_score = 0.0
            matched_by = "canonical_name"
            for candidate, candidate_type in candidates:
                candidate_normalized = normalize_name(candidate)
                score = (
                    1.0
                    if candidate_normalized == normalized
                    else SequenceMatcher(None, normalized, candidate_normalized).ratio()
                )
                if score > best_score:
                    best_score = score
                    matched_by = candidate_type
            if best_score >= 0.6:
                suggestions.append(
                    DuplicateSuggestion(
                        id=topic.id,
                        canonical_name=topic.canonical_name,
                        score=round(best_score, 3),
                        matched_by=matched_by,
                    )
                )
        return tuple(sorted(suggestions, key=lambda item: (-item.score, item.id))[:limit])

    @staticmethod
    def _validate_role_profile(profile: dict[str, Any]) -> None:
        role = profile.get("role")
        level = profile.get("level")
        if not isinstance(role, str) or not role.strip():
            raise DomainValidationError("Role profile requires a non-empty 'role'.")
        if not isinstance(level, str) or not level.strip():
            raise DomainValidationError("Role profile requires a non-empty 'level'.")
        if len(json_bytes := str(profile).encode()) > 100_000:
            raise DomainValidationError(
                f"Role profile is too large ({len(json_bytes)} bytes; maximum 100000)."
            )

    @staticmethod
    def _validate_requirements(
        requirements: Sequence[RequirementInput],
        *,
        kind: str,
    ) -> tuple[RequirementInput, ...]:
        seen: set[str] = set()
        result: list[RequirementInput] = []
        for item in requirements:
            if item.subject_id in seen:
                raise DomainValidationError(f"Duplicate {kind} requirement: {item.subject_id}")
            seen.add(item.subject_id)
            result.append(
                RequirementInput(
                    subject_id=item.subject_id,
                    required_level=require_level(item.required_level),
                    weight=require_weight(item.weight),
                    critical=item.critical,
                    minimum_evidence_count=require_evidence_count(
                        item.minimum_evidence_count
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _requirement_payload(item: RequirementInput) -> dict[str, Any]:
        return {
            "subject_id": item.subject_id,
            "required_level": item.required_level,
            "weight": item.weight,
            "critical": item.critical,
            "minimum_evidence_count": item.minimum_evidence_count,
        }

    @staticmethod
    def _requirement_diff(
        older: Sequence[Any],
        newer: Sequence[Any],
    ) -> dict[str, Any]:
        old_map = {item.subject_id: item for item in older}
        new_map = {item.subject_id: item for item in newer}
        shared = old_map.keys() & new_map.keys()
        return {
            "added": sorted(new_map.keys() - old_map.keys()),
            "removed": sorted(old_map.keys() - new_map.keys()),
            "changed": sorted(
                subject_id
                for subject_id in shared
                if old_map[subject_id] != new_map[subject_id]
            ),
        }
