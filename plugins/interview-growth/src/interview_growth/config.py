"""Runtime paths and filesystem safety rules."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .domain.errors import DomainValidationError

_GOAL_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@dataclass(frozen=True, slots=True)
class DataPaths:
    """All writable paths used by Interview Growth."""

    root: Path

    @classmethod
    def from_environment(cls) -> DataPaths:
        """Resolve plugin data without depending on the current working directory."""

        override = os.environ.get("INTERVIEW_GROWTH_DATA_DIR")
        if override:
            return cls(Path(override).expanduser().resolve())

        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            return cls((Path(xdg_data_home).expanduser() / "interview-growth").resolve())
        if sys.platform == "darwin":
            return cls(
                (Path.home() / "Library" / "Application Support" / "Interview Growth").resolve()
            )
        return cls((Path.home() / ".local" / "share" / "interview-growth").resolve())

    @property
    def registry_database(self) -> Path:
        return self.root / "registry.sqlite"

    @property
    def goals_directory(self) -> Path:
        return self.root / "goals"

    @property
    def backups_directory(self) -> Path:
        return self.root / "backups"

    @property
    def trash_directory(self) -> Path:
        return self.root / "trash"

    def goal_directory(self, goal_id: str) -> Path:
        self._validate_goal_id(goal_id)
        return self.goals_directory / goal_id

    def goal_database(self, goal_id: str) -> Path:
        return self.goal_directory(goal_id) / "goal.sqlite"

    def ensure_layout(self) -> None:
        """Create the private data directories if they do not exist."""

        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.goals_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.backups_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.trash_directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def _validate_goal_id(goal_id: str) -> None:
        if _GOAL_ID_PATTERN.fullmatch(goal_id) is None:
            raise DomainValidationError("Goal IDs must be canonical lowercase UUIDs.")
