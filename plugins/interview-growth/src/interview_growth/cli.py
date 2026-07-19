"""Deterministic local CLI for diagnostics and development."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from interview_growth.application.context import ContextService
from interview_growth.application.goals import GoalService
from interview_growth.config import DataPaths
from interview_growth.contracts import ContextPacketOutput, DoctorOutput, GoalListOutput, GoalOutput
from interview_growth.domain.models import ContextRole, GoalLifecycle


def _json_dump(value: BaseModel | dict[str, Any]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="interview-growth")
    parser.add_argument("--data-dir", type=Path, help="Override the persistent data directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize registry storage")
    subparsers.add_parser("doctor", help="Validate registry and goal database isolation")
    subparsers.add_parser("list", help="List registry-level goal summaries")

    create = subparsers.add_parser("create", help="Create an isolated growth goal")
    create.add_argument("--name", required=True)
    create.add_argument("--idempotency-key", required=True)
    create.add_argument("--slug")

    select = subparsers.add_parser("select", help="Bind a session to one goal")
    select.add_argument("--session-id", required=True)
    select.add_argument("--goal-id", required=True)

    current = subparsers.add_parser("current", help="Get the current goal for a session")
    current.add_argument("--session-id", required=True)

    lifecycle = subparsers.add_parser("lifecycle", help="Change current goal lifecycle")
    lifecycle.add_argument("--session-id", required=True)
    lifecycle.add_argument("--to", choices=[item.value for item in GoalLifecycle], required=True)

    context = subparsers.add_parser("context", help="Build a minimal Context Packet")
    context.add_argument("--session-id", required=True)
    context.add_argument("--role", choices=[item.value for item in ContextRole], required=True)
    context.add_argument("--task", default="session_resume")
    context.add_argument("--max-tokens", type=int, default=1200)
    return parser


def main() -> None:
    args = _parser().parse_args()
    paths = (
        DataPaths(args.data_dir.expanduser().resolve())
        if args.data_dir
        else DataPaths.from_environment()
    )
    goals = GoalService(paths)

    if args.command == "init":
        _json_dump({"ok": True, "data_dir": str(paths.root)})
    elif args.command == "doctor":
        output = DoctorOutput.from_domain(goals.doctor())
        _json_dump(output)
        if not output.ok:
            raise SystemExit(1)
    elif args.command == "list":
        _json_dump(
            GoalListOutput(
                goals=tuple(GoalOutput.from_domain(goal) for goal in goals.list_goals())
            )
        )
    elif args.command == "create":
        _json_dump(
            GoalOutput.from_domain(
                goals.create_goal(
                    name=args.name,
                    slug=args.slug,
                    idempotency_key=args.idempotency_key,
                )
            )
        )
    elif args.command == "select":
        _json_dump(
            GoalOutput.from_domain(
                goals.select_goal(session_id=args.session_id, goal_id=args.goal_id)
            )
        )
    elif args.command == "current":
        _json_dump(GoalOutput.from_domain(goals.get_current_goal(session_id=args.session_id)))
    elif args.command == "lifecycle":
        _json_dump(
            GoalOutput.from_domain(
                goals.change_current_goal_lifecycle(
                    session_id=args.session_id,
                    requested=GoalLifecycle(args.to),
                )
            )
        )
    elif args.command == "context":
        packet = ContextService(goals).build(
            session_id=args.session_id,
            role=ContextRole(args.role),
            task=args.task,
            max_tokens=args.max_tokens,
        )
        _json_dump(ContextPacketOutput.from_domain(packet))
    else:  # pragma: no cover - argparse enforces a known command
        raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
