from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from interview_growth.cli import describe_operation
from interview_growth.operations import OPERATIONS


def _call_cli(
    project_directory: Path,
    data_directory: Path,
    operation: str,
    payload: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "interview_growth.cli",
            "--data-dir",
            str(data_directory),
            "call",
            operation,
        ],
        cwd=project_directory,
        env={
            **os.environ,
            "PYTHONPATH": str(project_directory / "src"),
        },
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def _output(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    value = json.loads(process.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_structured_cli_lists_all_domain_operations(tmp_path: Path) -> None:
    project_directory = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, "-m", "interview_growth.cli", "operations"],
        cwd=project_directory,
        env={
            **os.environ,
            "PYTHONPATH": str(project_directory / "src"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = _output(process)
    assert result["ok"] is True
    names = {item["name"] for item in result["data"]}
    assert {
        "goal_create",
        "goal_select",
        "context_build",
        "standard_create_draft",
        "role_profile_get_current",
        "role_profile_update_draft",
        "question_capture",
        "interview_start",
        "attempt_record",
        "evaluation_submit",
        "dashboard_get",
        "real_interview_record",
        "goal_export",
        "goal_delete",
    } <= names
    assert len(names) == 54


def test_role_profile_operation_exposes_structured_fields() -> None:
    description = describe_operation("role_profile_update_draft")
    schema = description["parameters"]["role_profile"]["schema"]
    assert {"role", "level", "company_types", "technologies"} <= set(schema["properties"])


def test_every_operation_exposes_a_json_schema() -> None:
    for name in OPERATIONS:
        description = describe_operation(name)
        assert description["name"] == name
        assert description["description"]
        assert isinstance(description["parameters"], dict)
        assert isinstance(description["output_schema"], dict)
        json.dumps(description)


def test_structured_cli_calls_goal_operations_over_stdin(tmp_path: Path) -> None:
    project_directory = Path(__file__).resolve().parents[1]
    data_directory = tmp_path / "cli-data"
    created = _call_cli(
        project_directory,
        data_directory,
        "goal_create",
        {"name": "Agent Engineer", "idempotency_key": "cli-smoke-goal"},
    )
    assert created.returncode == 0, created.stderr
    result = _output(created)
    assert result["ok"] is True
    assert result["data"]["name"] == "Agent Engineer"
    assert result["error"] is None
    goal_id = str(result["data"]["id"])
    assert (data_directory / "registry.sqlite").is_file()
    assert len(tuple((data_directory / "goals").glob("*/goal.sqlite"))) == 1

    selected = _call_cli(
        project_directory,
        data_directory,
        "goal_select",
        {"session_id": "cli-session", "goal_id": goal_id},
    )
    assert selected.returncode == 0, selected.stderr
    current_profile = _call_cli(
        project_directory,
        data_directory,
        "role_profile_get_current",
        {"session_id": "cli-session"},
    )
    assert current_profile.returncode == 0, current_profile.stderr
    assert _output(current_profile)["data"] == {
        "configured": False,
        "role_profile": None,
        "standard_version_id": None,
        "version_number": None,
        "approved_at": None,
    }
    transitioned = _call_cli(
        project_directory,
        data_directory,
        "goal_change_lifecycle",
        {"session_id": "cli-session", "lifecycle": "in_progress"},
    )
    assert transitioned.returncode == 0, transitioned.stderr
    assert _output(transitioned)["data"]["lifecycle"] == "in_progress"

    listed = _call_cli(project_directory, data_directory, "goal_list", {})
    assert listed.returncode == 0, listed.stderr
    assert len(_output(listed)["data"]["goals"]) == 1


def test_structured_cli_returns_machine_readable_validation_errors(tmp_path: Path) -> None:
    project_directory = Path(__file__).resolve().parents[1]
    process = _call_cli(
        project_directory,
        tmp_path / "cli-data",
        "goal_create",
        {"name": "Missing idempotency key"},
    )
    assert process.returncode == 2
    result = _output(process)
    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "value"
    assert "idempotency_key" in result["error"]["message"]
