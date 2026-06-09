from __future__ import annotations


def test_domain_tool_manifest_exposes_agent_operable_commands():
    from insightbot.domain.tool_manifest import get_tool_manifest

    manifest = get_tool_manifest()
    tool_names = {tool["name"] for tool in manifest["tools"]}

    assert manifest["name"] == "InsightBot Domain Tools"
    assert manifest["version"] == 1
    assert {
        "list_tasks",
        "list_task_cards",
        "get_workspace_state",
        "get_task_spec",
        "get_task_status",
        "get_latest_run_evidence",
        "get_source_health_summary",
        "validate_task",
        "dry_run_task",
        "run_task",
        "propose_task_changeset",
        "propose_task_update",
        "apply_changeset",
        "approve_and_apply_changeset",
        "create_task",
        "delete_task",
    }.issubset(tool_names)

    by_name = {tool["name"]: tool for tool in manifest["tools"]}
    assert by_name["get_task_spec"]["risk_level"] == "low"
    assert by_name["dry_run_task"]["risk_level"] == "low"
    assert by_name["list_task_cards"]["requires_approval"] is False
    assert by_name["get_workspace_state"]["requires_approval"] is False
    assert by_name["get_latest_run_evidence"]["requires_approval"] is False
    assert by_name["get_source_health_summary"]["requires_approval"] is False
    assert by_name["run_task"]["risk_level"] == "high"
    assert by_name["run_task"]["requires_approval"] is True
    assert by_name["apply_changeset"]["requires_approval"] is True
    assert by_name["approve_and_apply_changeset"]["requires_approval"] is True
    assert by_name["get_task_spec"]["input_schema"]["required"] == ["task_id"]
    assert by_name["get_task_status"]["input_schema"]["required"] == ["task_id"]
    assert by_name["propose_task_changeset"]["input_schema"]["required"] == [
        "task_id",
        "target_task_definition",
        "intent",
    ]
    assert by_name["propose_task_update"]["input_schema"]["required"] == [
        "task_id",
        "target_task_definition",
        "intent",
    ]


def test_scheduler_can_return_tool_manifest():
    from insightbot.scheduler import Scheduler

    sched = Scheduler.__new__(Scheduler)
    manifest = sched.tool_manifest()

    assert manifest["name"] == "InsightBot Domain Tools"
    assert any(tool["name"] == "validate_task" for tool in manifest["tools"])
