"""Thin lifecycle hook entry point; business semantics remain in Skills and services."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

from interview_growth.application.goals import GoalService
from interview_growth.application.interviews import InterviewService
from interview_growth.config import DataPaths
from interview_growth.domain.errors import InterviewGrowthError


def _read_hook_input() -> dict[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Hook input must be a JSON object.")
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="interview-growth-hook")
    parser.add_argument("command", choices=["healthcheck", "checkpoint"])
    args = parser.parse_args()
    payload = _read_hook_input()
    goals = GoalService(DataPaths.from_environment())

    if args.command == "healthcheck":
        report = goals.doctor()
        if not report.ok:
            for issue in report.issues:
                print(issue, file=sys.stderr)
            raise SystemExit(1)
    elif args.command == "checkpoint":
        raw_session_id = payload.get("session_id", payload.get("sessionId"))
        if not isinstance(raw_session_id, str) or not raw_session_id.strip():
            return
        interviews = InterviewService(goals)
        try:
            active = interviews.find_active(session_id=raw_session_id)
            if active is None:
                return
            raw_event = payload.get("hook_event_name", "pre_compact")
            event = raw_event if isinstance(raw_event, str) else "pre_compact"
            interviews.checkpoint(
                session_id=raw_session_id,
                interview_id=active.id,
                expected_revision=active.revision,
                reason=f"hook:{event}",
                idempotency_key=(
                    f"hook:{event}:{raw_session_id}:{active.id}:r{active.revision}"
                ),
            )
        except InterviewGrowthError:
            return


if __name__ == "__main__":
    main()
