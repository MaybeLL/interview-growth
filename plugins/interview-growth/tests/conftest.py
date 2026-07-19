from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from interview_growth.application.goals import GoalService
from interview_growth.config import DataPaths

GOAL_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)


@pytest.fixture
def data_paths(tmp_path: Path) -> DataPaths:
    return DataPaths(tmp_path / "data")


@pytest.fixture
def goal_service_factory(
    data_paths: DataPaths,
) -> Callable[[], GoalService]:
    def build() -> GoalService:
        ids: Iterator[str] = iter(GOAL_IDS)
        timestamps: Iterator[str] = iter(
            (
                "2026-07-19T10:00:00.000Z",
                "2026-07-19T10:01:00.000Z",
                "2026-07-19T10:02:00.000Z",
                "2026-07-19T10:03:00.000Z",
                "2026-07-19T10:04:00.000Z",
            )
        )
        return GoalService(
            data_paths,
            id_factory=lambda: next(ids),
            clock=lambda: next(timestamps),
        )

    return build
