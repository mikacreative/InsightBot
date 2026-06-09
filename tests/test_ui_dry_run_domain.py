from __future__ import annotations


def test_command_result_to_ui_result_preserves_domain_metadata():
    from insightbot.domain import CommandResult, DiagnosisReport, RunTrace, TaskSpec, TaskVersion
    from scripts.ui.dry_run import _command_result_to_ui_result

    spec = TaskSpec.from_task_definition(
        "daily",
        {
            "name": "Daily",
            "enabled": True,
            "pipeline": "editorial",
            "sections": {"Marketing": {"prompt": "Keep marketing news."}},
            "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
            "channels": ["wecom_main"],
        },
    )
    version = TaskVersion.from_spec(spec, created_at="2026-06-06T00:00:00+00:00")
    run_result = {
        "ok": True,
        "task_id": "daily",
        "pipeline": "editorial",
        "dry_run": True,
        "stage_results": {"global_candidates": []},
        "channel_results": [],
        "final_markdown": "",
    }
    trace = RunTrace.from_task_result(run_result, task_version_id=version.version_id, trigger_type="dry_run")
    diagnosis = DiagnosisReport.from_run_trace(trace)

    ui_result = _command_result_to_ui_result(
        CommandResult(
            command="dry_run_task",
            ok=True,
            task_spec=spec,
            task_version=version,
            run_result=run_result,
            run_trace=trace,
            diagnosis=diagnosis,
        )
    )

    assert ui_result["task_id"] == "daily"
    assert ui_result["_domain_command"] == "dry_run_task"
    assert ui_result["_task_version"]["version_id"] == version.version_id
    assert ui_result["_run_trace"]["task_version_id"] == version.version_id
    assert ui_result["_diagnosis"]["findings"][0]["type"] == "empty_candidates"


def test_command_result_to_ui_result_supports_manual_run_command():
    from insightbot.domain import CommandResult, DiagnosisReport, RunTrace, TaskSpec, TaskVersion
    from scripts.ui.dry_run import _command_result_to_ui_result

    spec = TaskSpec.from_task_definition(
        "daily",
        {
            "name": "Daily",
            "enabled": True,
            "pipeline": "editorial",
            "sections": {"Marketing": {"prompt": "Keep marketing news."}},
            "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
            "channels": ["wecom_main"],
        },
    )
    version = TaskVersion.from_spec(spec, created_at="2026-06-06T00:00:00+00:00")
    run_result = {
        "ok": True,
        "task_id": "daily",
        "pipeline": "editorial",
        "dry_run": False,
        "stage_results": {
            "global_candidates": [{"id": "c1"}],
            "screened_result": {"screened": [{"id": "c1"}]},
            "assignment_result": {"category_candidate_map": {"Marketing": [{"id": "c1"}]}, "unassigned": []},
            "category_results": {"Marketing": {"selected_items": [{"title": "A"}]}},
        },
        "channel_results": [{"channel_id": "wecom_main", "ok": True}],
        "final_markdown": "### A\n> summary",
    }
    trace = RunTrace.from_task_result(run_result, task_version_id=version.version_id, trigger_type="manual")
    diagnosis = DiagnosisReport.from_run_trace(trace)

    ui_result = _command_result_to_ui_result(
        CommandResult(
            command="run_task",
            ok=True,
            task_spec=spec,
            task_version=version,
            run_result=run_result,
            run_trace=trace,
            diagnosis=diagnosis,
        )
    )

    assert ui_result["dry_run"] is False
    assert ui_result["_domain_command"] == "run_task"
    assert ui_result["_run_trace"]["trigger_type"] == "manual"
    assert ui_result["_run_trace"]["stages"][-1]["stage"] == "send"
