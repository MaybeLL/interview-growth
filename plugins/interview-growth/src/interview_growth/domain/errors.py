"""Domain-specific exceptions."""


class InterviewGrowthError(Exception):
    """Base exception for expected Interview Growth failures."""


class DomainValidationError(InterviewGrowthError):
    """Raised when a domain command contains invalid input."""


class GoalNotFoundError(InterviewGrowthError):
    """Raised when a goal identifier is unknown."""


class NoCurrentGoalError(InterviewGrowthError):
    """Raised when a session has no explicitly selected goal."""


class InvalidLifecycleTransitionError(InterviewGrowthError):
    """Raised when a goal lifecycle transition is not allowed."""


class IdempotencyConflictError(InterviewGrowthError):
    """Raised when an idempotency key is reused for a different request."""


class VersionConflictError(InterviewGrowthError):
    """Raised when a write is based on a stale expected version."""
