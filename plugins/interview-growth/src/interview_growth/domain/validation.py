"""Shared validation and canonicalization for domain commands."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from typing import Any

from .errors import DomainValidationError


def new_id() -> str:
    return str(uuid.uuid4())


def require_text(value: str, *, field: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError(f"{field} must not be empty.")
    if len(normalized) > maximum:
        raise DomainValidationError(f"{field} must be at most {maximum} characters.")
    return normalized


def normalize_name(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_level(value: int) -> int:
    if value < 0 or value > 4:
        raise DomainValidationError("Required level must be between 0 and 4.")
    return value


def require_weight(value: float) -> float:
    if value <= 0 or value > 100:
        raise DomainValidationError("Requirement weight must be greater than 0 and at most 100.")
    return value


def require_evidence_count(value: int) -> int:
    if value < 1 or value > 100:
        raise DomainValidationError("Minimum evidence count must be between 1 and 100.")
    return value
