from __future__ import annotations


def _sample_task() -> dict:
    return {
        "name": "营销日报",
        "enabled": True,
        "pipeline": "editorial",
        "sources": {
            "rss": [
                {
                    "id": "digitaling",
                    "name": "数英",
                    "url": "https://www.digitaling.com/feed",
                    "enabled": True,
                    "section_hints": ["💡 营销行业"],
                },
                {
                    "id": "disabled",
                    "name": "Disabled",
                    "url": "https://example.com/disabled.xml",
                    "enabled": False,
                },
            ],
            "search": {
                "enabled": True,
                "provider": "brave",
                "queries": [
                    {"keywords": "AI 营销", "section_hints": ["🤖 数智前沿"], "max_results": 8}
                ],
            },
        },
        "sections": {
            "💡 营销行业": {
                "prompt": "保留营销传播案例。",
                "keywords": ["营销", "品牌"],
                "source_hints": ["marketing"],
            },
            "🤖 数智前沿": {
                "prompt": "保留营销相关 AI 应用。",
                "keywords": ["AI"],
                "source_hints": ["digital"],
            },
        },
        "pipeline_config": {"max_items_per_section": 5, "allow_empty_sections": True},
        "channels": ["wecom_main"],
        "schedule": {"hour": 8, "minute": 30},
    }


def test_task_spec_from_current_task_shape_normalizes_core_fields():
    from insightbot.domain import TaskSpec

    spec = TaskSpec.from_task_definition("Daily_brief", _sample_task())

    assert spec.task_id == "Daily_brief"
    assert spec.name == "营销日报"
    assert spec.pipeline == "editorial"
    assert spec.section_names == ["💡 营销行业", "🤖 数智前沿"]
    assert spec.enabled_source_count == 1
    assert spec.channels == ["wecom_main"]
    assert spec.schedule == {"hour": 8, "minute": 30}
    assert spec.quality_policy["max_items_per_section"] == 5
    assert spec.to_dict()["sources"]["rss"][0]["source_id"] == "digitaling"


def test_task_version_fingerprint_is_stable_for_equivalent_specs():
    from insightbot.domain import TaskSpec, TaskVersion

    task_a = _sample_task()
    task_b = _sample_task()
    task_b["sources"]["rss"] = list(reversed(task_b["sources"]["rss"]))

    version_a = TaskVersion.from_spec(TaskSpec.from_task_definition("Daily_brief", task_a))
    version_b = TaskVersion.from_spec(TaskSpec.from_task_definition("Daily_brief", task_b))

    assert version_a.fingerprint == version_b.fingerprint
    assert version_a.version_id.startswith("taskv_")


def test_run_trace_extracts_existing_task_runner_result_shape():
    from insightbot.domain import RunTrace

    result = {
        "ok": True,
        "dry_run": True,
        "pipeline": "editorial",
        "task_id": "Daily_brief",
        "stage_results": {
            "global_candidates": [{"id": "c1"}, {"id": "c2"}],
            "screened_result": {"screened": [{"id": "c1"}]},
            "assignment_result": {
                "category_candidate_map": {"💡 营销行业": [{"id": "c1"}]},
                "unassigned": [{"id": "c2"}],
            },
            "category_results": {
                "💡 营销行业": {"selected_items": [{"title": "A"}]},
                "🤖 数智前沿": {"selected_items": []},
            },
        },
        "channel_results": [],
        "final_markdown": "### A\n> summary",
    }

    trace = RunTrace.from_task_result(result, task_version_id="taskv_123", trigger_type="dry_run")

    assert trace.task_id == "Daily_brief"
    assert trace.task_version_id == "taskv_123"
    assert trace.trigger_type == "dry_run"
    assert trace.stage("fetch").output_count == 2
    assert trace.stage("screen").output_count == 1
    assert trace.stage("assign").warning_count == 1
    assert trace.stage("generate").output_count == 1
    assert trace.to_dict()["stages"][0]["stage"] == "fetch"


def test_diagnosis_reports_task_and_run_findings():
    from insightbot.domain import DiagnosisReport, RunTrace, TaskSpec

    invalid_spec = TaskSpec.from_task_definition(
        "empty_task",
        {"name": "空任务", "enabled": True, "pipeline": "editorial", "sections": {}, "sources": {}, "channels": []},
    )
    task_report = DiagnosisReport.from_task_spec(invalid_spec)

    assert {finding.type for finding in task_report.findings} >= {
        "missing_sections",
        "missing_sources",
        "missing_channels",
    }

    trace = RunTrace.from_task_result(
        {
            "ok": False,
            "dry_run": False,
            "pipeline": "editorial",
            "task_id": "Daily_brief",
            "stage_results": {
                "global_candidates": [],
                "category_results": {"💡 营销行业": {"selected_items": []}},
            },
            "channel_results": [{"channel_id": "wecom_main", "ok": False, "error": "token expired"}],
            "final_markdown": "",
            "error": "send failed",
        },
        task_version_id="taskv_123",
        trigger_type="manual",
    )
    run_report = DiagnosisReport.from_run_trace(trace)

    assert {finding.type for finding in run_report.findings} >= {
        "empty_candidates",
        "empty_final_output",
        "channel_failure",
    }


def test_commands_build_spec_validation_and_dry_run_trace():
    from insightbot.domain.commands import dry_run_task, get_task_spec, run_task, validate_task

    tasks = {"tasks": {"Daily_brief": _sample_task()}}
    spec = get_task_spec(tasks, "Daily_brief")

    assert spec.task_id == "Daily_brief"
    _spec, validation_report = validate_task(tasks, "Daily_brief")
    assert validation_report.severity == "ok"

    def fake_runner(task_id: str, *, dry_run: bool) -> dict:
        assert task_id == "Daily_brief"
        assert dry_run is True
        return {
            "ok": True,
            "dry_run": True,
            "pipeline": "editorial",
            "task_id": task_id,
            "stage_results": {
                "global_candidates": [{"id": "c1"}],
                "screened_result": {"screened": [{"id": "c1"}]},
                "assignment_result": {
                    "category_candidate_map": {"💡 营销行业": [{"id": "c1"}]},
                    "unassigned": [],
                },
                "category_results": {"💡 营销行业": {"selected_items": [{"title": "A"}]}},
            },
            "channel_results": [],
            "final_markdown": "### A\n> summary",
        }

    command_result = dry_run_task(tasks, "Daily_brief", run_task_fn=fake_runner)

    assert command_result.ok is True
    assert command_result.command == "dry_run_task"
    assert command_result.task_version.version_id.startswith("taskv_")
    assert command_result.run_trace.task_version_id == command_result.task_version.version_id
    assert command_result.diagnosis.severity == "ok"
    assert command_result.to_dict()["run_trace"]["stages"][0]["stage"] == "fetch"

    def fake_real_runner(task_id: str, *, dry_run: bool) -> dict:
        assert task_id == "Daily_brief"
        assert dry_run is False
        return {
            "ok": True,
            "dry_run": False,
            "pipeline": "editorial",
            "task_id": task_id,
            "stage_results": {
                "global_candidates": [{"id": "c1"}],
                "screened_result": {"screened": [{"id": "c1"}]},
                "assignment_result": {
                    "category_candidate_map": {"💡 营销行业": [{"id": "c1"}]},
                    "unassigned": [],
                },
                "category_results": {"💡 营销行业": {"selected_items": [{"title": "A"}]}},
            },
            "channel_results": [{"channel_id": "wecom_main", "ok": True}],
            "final_markdown": "### A\n> summary",
        }

    real_result = run_task(tasks, "Daily_brief", run_task_fn=fake_real_runner)

    assert real_result.ok is True
    assert real_result.command == "run_task"
    assert real_result.run_trace.trigger_type == "manual"
    assert real_result.run_trace.task_version_id == real_result.task_version.version_id
    assert real_result.run_trace.stage("send").output_count == 1


def test_domain_validation_can_check_environment_and_export_legacy_validation_shape():
    from insightbot.domain.commands import validate_task
    from insightbot.domain.compat import validation_result_from_domain

    tasks = {
        "tasks": {
            "Daily_brief": {
                "name": "营销日报",
                "enabled": True,
                "pipeline": "editorial",
                "sections": {"营销": {"prompt": ""}},
                "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                "channels": ["missing_channel"],
                "schedule": {},
            }
        }
    }

    spec, report = validate_task(tasks, "Daily_brief", channels_payload={"channels": {"wecom_main": {}}})
    validation = validation_result_from_domain(spec, report)

    assert validation["task_id"] == "Daily_brief"
    assert validation["is_runnable"] is False
    assert validation["status"] == "not_ready"
    assert validation["summary"]["section_count"] == 1
    assert validation["summary"]["rss_source_count"] == 1
    codes = {issue["code"] for issue in validation["issues"]}
    assert "channel_not_found" in codes
    assert "missing_schedule" in codes
    assert "missing_section_prompt" in codes


def test_changeset_proposal_and_apply_are_structured_and_non_mutating():
    from insightbot.domain.commands import apply_changeset, get_task_spec, propose_task_changeset

    tasks = {"tasks": {"Daily_brief": _sample_task()}}
    target_task = _sample_task()
    target_task["name"] = "营销日报新版"
    target_task["channels"] = ["wecom_main", "wecom_backup"]
    target_task["pipeline_config"]["max_items_per_section"] = 7

    changeset = propose_task_changeset(
        tasks,
        "Daily_brief",
        target_task,
        intent="Update task name, channel, and item limit",
        rationale="Use backup channel and wider brief capacity.",
    )

    assert changeset.task_id == "Daily_brief"
    assert changeset.risk_level == "medium"
    assert changeset.base_version_id.startswith("taskv_")
    assert changeset.target_version_id.startswith("taskv_")
    assert changeset.base_version_id != changeset.target_version_id
    assert {op["path"] for op in changeset.operations} >= {
        "/name",
        "/channels",
        "/pipeline_config/max_items_per_section",
    }
    assert tasks["tasks"]["Daily_brief"]["name"] == "营销日报"

    updated = apply_changeset(tasks, changeset)
    updated_spec = get_task_spec(updated, "Daily_brief")

    assert updated["tasks"]["Daily_brief"]["name"] == "营销日报新版"
    assert updated_spec.channels == ["wecom_main", "wecom_backup"]
    assert updated_spec.quality_policy["max_items_per_section"] == 7
    assert tasks["tasks"]["Daily_brief"]["channels"] == ["wecom_main"]


def test_create_and_delete_task_commands_are_structured_and_non_mutating():
    from insightbot.domain.commands import create_task, delete_task, get_task_spec

    tasks = {"tasks": {"Daily_brief": _sample_task()}}
    new_task = _sample_task()
    new_task["name"] = "周报"
    new_task["schedule"] = {"hour": 9, "minute": 0}

    create_result = create_task(
        tasks,
        "Weekly_brief",
        new_task,
        intent="Create weekly brief task",
        rationale="Add a second task for weekly reporting.",
    )

    assert create_result.command == "create_task"
    assert create_result.ok is True
    assert create_result.changeset.task_id == "Weekly_brief"
    assert create_result.changeset.risk_level == "medium"
    assert tasks["tasks"].keys() == {"Daily_brief"}
    assert create_result.updated_tasks["tasks"]["Weekly_brief"]["name"] == "周报"
    assert get_task_spec(create_result.updated_tasks, "Weekly_brief").schedule == {"hour": 9, "minute": 0}

    delete_result = delete_task(
        create_result.updated_tasks,
        "Weekly_brief",
        intent="Delete weekly task",
        rationale="Remove unused test task.",
    )

    assert delete_result.command == "delete_task"
    assert delete_result.ok is True
    assert delete_result.changeset.risk_level == "high"
    assert "Weekly_brief" not in delete_result.updated_tasks["tasks"]
    assert "Weekly_brief" in create_result.updated_tasks["tasks"]


def test_domain_tool_manifest_describes_agent_safe_command_boundary():
    from insightbot.domain import get_tool_manifest

    manifest = get_tool_manifest()
    tools = {tool["name"]: tool for tool in manifest["tools"]}

    assert manifest["manifest_id"] == "insightbot_domain_tools_v1"
    assert {
        "get_task_spec",
        "validate_task",
        "dry_run_task",
        "run_task",
        "propose_task_changeset",
        "apply_changeset",
        "create_task",
        "delete_task",
    } <= set(tools)

    assert tools["get_task_spec"]["requires_approval"] is False
    assert tools["dry_run_task"]["risk_level"] == "low"
    assert tools["run_task"]["requires_approval"] is True
    assert tools["apply_changeset"]["requires_approval"] is True
    assert tools["delete_task"]["risk_level"] == "high"

    for tool in tools.values():
        assert tool["input_schema"]["type"] == "object"
        assert tool["output_schema"]["type"] == "object"
        assert isinstance(tool["description"], str) and tool["description"]
