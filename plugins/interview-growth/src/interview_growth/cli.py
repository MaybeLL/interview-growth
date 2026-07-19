"""Deterministic JSON CLI for agent workflows and local diagnostics."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, cast, get_type_hints

from pydantic import BaseModel, TypeAdapter, ValidationError

from interview_growth.application.context import ContextService
from interview_growth.application.goals import GoalService
from interview_growth.config import DataPaths
from interview_growth.contracts import ContextPacketOutput, DoctorOutput, GoalListOutput, GoalOutput
from interview_growth.domain.errors import InterviewGrowthError
from interview_growth.domain.models import ContextRole, GoalLifecycle
from interview_growth.operations import OPERATIONS

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def _json_value(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_value(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [_json_value(item) for item in sequence]
    raise TypeError(f"Value is not JSON serializable: {type(value).__name__}")


def _json_dump(value: object) -> None:
    payload = _json_value(value)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _success(value: object) -> dict[str, object]:
    return {"ok": True, "data": _json_value(value), "error": None}


def _failure(code: str, message: str, details: object = None) -> dict[str, object]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details},
    }


def _error_code(error: Exception) -> str:
    name = error.__class__.__name__
    pieces: list[str] = []
    for index, character in enumerate(name):
        if character.isupper() and index:
            pieces.append("_")
        pieces.append(character.lower())
    return "".join(pieces).removesuffix("_error")


def _read_call_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json is not None:
        raw = args.input_json
    elif args.input_file is not None:
        raw = args.input_file.read_text(encoding="utf-8")
    elif sys.stdin.isatty():
        raw = "{}"
    else:
        raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("CLI operation input must be a JSON object.")
    return cast(dict[str, Any], payload)


def _invoke_operation(name: str, payload: dict[str, Any]) -> Any:
    function = OPERATIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown operation: {name}")

    signature = inspect.signature(function)
    unexpected = sorted(set(payload) - set(signature.parameters))
    if unexpected:
        raise ValueError(f"Unexpected input fields: {', '.join(unexpected)}")

    hints = get_type_hints(function)
    arguments: dict[str, Any] = {}
    missing: list[str] = []
    for parameter_name, parameter in signature.parameters.items():
        if parameter_name not in payload:
            if parameter.default is inspect.Parameter.empty:
                missing.append(parameter_name)
            continue
        annotation = hints.get(parameter_name, Any)
        arguments[parameter_name] = TypeAdapter(annotation).validate_python(
            payload[parameter_name]
        )
    if missing:
        raise ValueError(f"Missing required input fields: {', '.join(missing)}")
    return function(**arguments)


def describe_operation(name: str) -> dict[str, Any]:
    function = OPERATIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown operation: {name}")
    signature = inspect.signature(function)
    hints = get_type_hints(function)
    parameters: dict[str, Any] = {}
    for parameter_name, parameter in signature.parameters.items():
        annotation = hints.get(parameter_name, Any)
        value: dict[str, Any] = {
            "required": parameter.default is inspect.Parameter.empty,
            "schema": TypeAdapter(annotation).json_schema(),
        }
        if parameter.default is not inspect.Parameter.empty:
            value["default"] = _json_value(parameter.default)
        parameters[parameter_name] = value
    return {
        "name": name,
        "description": inspect.getdoc(function) or "",
        "parameters": parameters,
        "output_schema": TypeAdapter(hints.get("return", Any)).json_schema(),
    }


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

    call = subparsers.add_parser(
        "call", help="Invoke one structured domain operation with JSON input"
    )
    call.add_argument("operation", choices=sorted(OPERATIONS))
    call_input = call.add_mutually_exclusive_group()
    call_input.add_argument("--input-json", help="Inline JSON object; defaults to stdin")
    call_input.add_argument("--input-file", type=Path, help="Read the JSON object from a file")

    operations = subparsers.add_parser("operations", help="List structured CLI operations")
    operations.add_argument("operation", nargs="?", choices=sorted(OPERATIONS))
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.data_dir:
        os.environ["INTERVIEW_GROWTH_DATA_DIR"] = str(args.data_dir.expanduser().resolve())

    if args.command == "call":
        try:
            result = _invoke_operation(args.operation, _read_call_payload(args))
        except (InterviewGrowthError, ValidationError, ValueError, json.JSONDecodeError) as error:
            details = (
                error.errors(include_url=False)
                if isinstance(error, ValidationError)
                else None
            )
            _json_dump(_failure(_error_code(error), str(error), details))
            raise SystemExit(2) from None
        _json_dump(_success(result))
        return

    if args.command == "operations":
        try:
            result = (
                describe_operation(args.operation)
                if args.operation
                else [
                    {
                        "name": name,
                        "description": inspect.getdoc(function) or "",
                    }
                    for name, function in sorted(OPERATIONS.items())
                ]
            )
        except ValueError as error:
            _json_dump(_failure(_error_code(error), str(error)))
            raise SystemExit(2) from None
        _json_dump(_success(result))
        return

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
