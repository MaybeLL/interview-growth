"""Question capture, immutable versioning, search, and duplicate suggestions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, cast

from interview_growth.application.goals import GoalService, utc_now
from interview_growth.domain.errors import DomainValidationError
from interview_growth.domain.models import Question, QuestionStatus, QuestionVersion
from interview_growth.domain.validation import new_id, normalize_name, request_hash, require_text
from interview_growth.persistence.question_repository import QuestionRepository


@dataclass(frozen=True, slots=True)
class QuestionDuplicateSuggestion:
    question_id: str
    prompt: str
    score: float


class QuestionBankService:
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

    def capture(
        self,
        *,
        session_id: str,
        prompt: str,
        source: str,
        topic_ids: Sequence[str],
        capability_ids: Sequence[str],
        idempotency_key: str,
    ) -> Question:
        clean_prompt = require_text(prompt, field="Question prompt", maximum=20_000)
        clean_source = require_text(source, field="Question source", maximum=200)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        topics = tuple(dict.fromkeys(topic_ids))
        capabilities = tuple(dict.fromkeys(capability_ids))
        timestamp = self._clock()
        question_id = self._id_factory()
        version = QuestionVersion(
            question_id=question_id,
            version=1,
            prompt=clean_prompt,
            intent=None,
            rubric=None,
            topic_ids=topics,
            capability_ids=capabilities,
            created_at=timestamp,
        )
        question = Question(
            id=question_id,
            status=QuestionStatus.PENDING,
            source=clean_source,
            current_version=1,
            created_at=timestamp,
            updated_at=timestamp,
            retired_at=None,
            version=version,
        )
        return self._repository(session_id).capture(
            question=question,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "prompt": clean_prompt,
                    "source": clean_source,
                    "topic_ids": sorted(topics),
                    "capability_ids": sorted(capabilities),
                }
            ),
        )

    def prepare_version(
        self,
        *,
        session_id: str,
        question_id: str,
        expected_current_version: int,
        prompt: str,
        intent: str,
        rubric: Mapping[str, Any],
        topic_ids: Sequence[str],
        capability_ids: Sequence[str],
        idempotency_key: str,
    ) -> Question:
        if expected_current_version < 1:
            raise DomainValidationError("Expected question version must be positive.")
        clean_prompt = require_text(prompt, field="Question prompt", maximum=20_000)
        clean_intent = require_text(intent, field="Evaluation intent", maximum=2000)
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        clean_rubric = dict(rubric)
        self._validate_rubric(clean_rubric)
        topics = tuple(dict.fromkeys(topic_ids))
        capabilities = tuple(dict.fromkeys(capability_ids))
        if not topics or not capabilities:
            raise DomainValidationError(
                "An assessable question requires at least one topic and one capability."
            )
        timestamp = self._clock()
        version = QuestionVersion(
            question_id=question_id,
            version=expected_current_version + 1,
            prompt=clean_prompt,
            intent=clean_intent,
            rubric=clean_rubric,
            topic_ids=topics,
            capability_ids=capabilities,
            created_at=timestamp,
        )
        return self._repository(session_id).prepare_version(
            version=version,
            expected_current_version=expected_current_version,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "question_id": question_id,
                    "expected_current_version": expected_current_version,
                    "prompt": clean_prompt,
                    "intent": clean_intent,
                    "rubric": clean_rubric,
                    "topic_ids": sorted(topics),
                    "capability_ids": sorted(capabilities),
                }
            ),
        )

    def search(
        self,
        *,
        session_id: str,
        query: str = "",
        topic_id: str | None = None,
        status: QuestionStatus | None = None,
        limit: int = 20,
    ) -> tuple[Question, ...]:
        if limit < 1 or limit > 100:
            raise DomainValidationError("Question search limit must be between 1 and 100.")
        return self._repository(session_id).search(
            query=" ".join(query.split()),
            topic_id=topic_id,
            status=status,
            limit=limit,
        )

    def get_history(self, *, session_id: str, question_id: str) -> tuple[QuestionVersion, ...]:
        return self._repository(session_id).history(question_id)

    def retire(
        self,
        *,
        session_id: str,
        question_id: str,
        expected_current_version: int,
        idempotency_key: str,
    ) -> Question:
        clean_key = require_text(idempotency_key, field="Idempotency key", maximum=200)
        timestamp = self._clock()
        return self._repository(session_id).retire(
            question_id=question_id,
            expected_current_version=expected_current_version,
            timestamp=timestamp,
            idempotency_key=clean_key,
            request_hash=request_hash(
                {
                    "question_id": question_id,
                    "expected_current_version": expected_current_version,
                }
            ),
        )

    def suggest_duplicates(
        self,
        *,
        session_id: str,
        prompt: str,
        limit: int = 5,
    ) -> tuple[QuestionDuplicateSuggestion, ...]:
        if limit < 1 or limit > 20:
            raise DomainValidationError("Duplicate suggestion limit must be between 1 and 20.")
        normalized = normalize_name(
            require_text(prompt, field="Question prompt", maximum=20_000)
        )
        suggestions: list[QuestionDuplicateSuggestion] = []
        for question in self._repository(session_id).list_recent():
            candidate = normalize_name(question.version.prompt)
            sequence_score = SequenceMatcher(None, normalized, candidate).ratio()
            left_tokens = set(normalized.split())
            right_tokens = set(candidate.split())
            union = left_tokens | right_tokens
            token_score = 0.0 if not union else len(left_tokens & right_tokens) / len(union)
            score = max(sequence_score, token_score)
            if score >= 0.65:
                suggestions.append(
                    QuestionDuplicateSuggestion(
                        question_id=question.id,
                        prompt=question.version.prompt,
                        score=round(score, 3),
                    )
                )
        return tuple(
            sorted(suggestions, key=lambda item: (-item.score, item.question_id))[:limit]
        )

    def counts(self, *, session_id: str) -> dict[str, int]:
        return self._repository(session_id).counts()

    def _repository(self, session_id: str) -> QuestionRepository:
        goal, database_path = self._goals.resolve_current_goal_database(session_id=session_id)
        return QuestionRepository(database_path, goal.id)

    @staticmethod
    def _validate_rubric(rubric: dict[str, Any]) -> None:
        required_list_fields = (
            "expected_evidence",
            "critical_omissions",
            "follow_up_directions",
        )
        intent = rubric.get("evaluation_intent")
        if not isinstance(intent, str) or not intent.strip():
            raise DomainValidationError("Rubric requires a non-empty evaluation_intent.")
        for field in required_list_fields:
            value = rubric.get(field)
            if not isinstance(value, list):
                raise DomainValidationError(f"Rubric field {field} must be a list of text.")
            items = cast(list[object], value)
            if any(not isinstance(item, str) or not item.strip() for item in items):
                raise DomainValidationError(f"Rubric field {field} must be a list of text.")
            if field == "expected_evidence" and not items:
                raise DomainValidationError("Rubric expected_evidence must not be empty.")
        anchors = rubric.get("level_anchors")
        if not isinstance(anchors, dict):
            raise DomainValidationError("Rubric level_anchors must define levels 0 through 4.")
        anchor_map = cast(dict[object, object], anchors)
        if set(anchor_map) != {"0", "1", "2", "3", "4"}:
            raise DomainValidationError("Rubric level_anchors must define levels 0 through 4.")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in anchor_map.values()
        ):
            raise DomainValidationError("Every rubric level anchor must be non-empty text.")
