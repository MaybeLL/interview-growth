"""Domain types and invariants."""

from .errors import (
    DomainValidationError,
    GoalNotFoundError,
    IdempotencyConflictError,
    InvalidLifecycleTransitionError,
    NoCurrentGoalError,
)
from .models import ContextRole, Goal, GoalLifecycle

__all__ = [
    "ContextRole",
    "DomainValidationError",
    "Goal",
    "GoalLifecycle",
    "GoalNotFoundError",
    "IdempotencyConflictError",
    "InvalidLifecycleTransitionError",
    "NoCurrentGoalError",
]
