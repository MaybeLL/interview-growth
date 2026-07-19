from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def test_stdio_server_lists_and_calls_goal_tools(tmp_path: Path) -> None:
    data_directory = tmp_path / "mcp-data"
    project_directory = Path(__file__).resolve().parents[1]

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "interview_growth.mcp_server"],
            cwd=project_directory,
            env={
                **os.environ,
                "INTERVIEW_GROWTH_DATA_DIR": str(data_directory),
                "PYTHONPATH": str(project_directory / "src"),
            },
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert {
                "goal_create",
                "goal_list",
                "goal_select",
                "goal_get_current",
                "goal_change_lifecycle",
                "context_build",
                "source_material_add",
                "topic_create",
                "topic_list",
                "topic_suggest_duplicates",
                "capability_create",
                "capability_list",
                "standard_create_draft",
                "standard_get_draft",
                "standard_approve",
                "standard_list_versions",
                "standard_compare_versions",
                "question_capture",
                "question_prepare_version",
                "question_search",
                "question_get_history",
                "question_suggest_duplicates",
                "question_retire",
                "interview_start",
                "interview_get_state",
                "interview_register_question",
                "followup_register",
                "attempt_record",
                "evaluation_submit",
                "interview_checkpoint",
                "interview_pause",
                "interview_resume",
                "interview_finish",
                "practice_record",
                "dashboard_get",
                "evidence_get",
                "gap_list",
                "evaluation_dispute",
                "evaluation_submit_reassessment",
                "evaluation_resolve_dispute",
                "prescription_create",
                "prescription_get_next",
                "retest_schedule",
                "real_interview_record",
                "real_interview_get",
                "real_interview_list",
                "goal_backup",
                "goal_list_backups",
                "goal_restore",
                "goal_export",
                "goal_import",
                "goal_delete",
            } <= tool_names

            result = await session.call_tool(
                "goal_create",
                {
                    "name": "Agent Engineer",
                    "idempotency_key": "stdio-smoke-goal",
                },
            )
            assert result.isError is not True

    anyio.run(exercise_server)
    assert (data_directory / "registry.sqlite").is_file()
    assert len(tuple((data_directory / "goals").glob("*/goal.sqlite"))) == 1
