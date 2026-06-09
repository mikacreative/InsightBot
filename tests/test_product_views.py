from __future__ import annotations


def _task_spec():
    from insightbot.domain import TaskSpec

    return TaskSpec.from_task_definition(
        "daily",
        {
            "name": "Daily Brief",
            "enabled": True,
            "pipeline": "editorial",
            "sections": {"Marketing": {"prompt": "Keep marketing news."}},
            "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
            "channels": ["wecom_main"],
            "schedule": {"hour": 8, "minute": 30},
        },
    )


def test_build_task_card_ready_state():
    from insightbot.product import build_task_card

    card = build_task_card(
        _task_spec(),
        {"is_runnable": True, "issues": [], "summary": {"task_version_id": "taskv_123"}},
        {"task_id": "daily", "ok": True, "final_markdown": "### A", "channel_results": [{"ok": True}]},
        {"task_id": "daily", "ok": True, "final_markdown": "### A", "channel_results": [{"ok": True}]},
        {"counts": {"total": 1, "ok": 1, "stale": 0, "error": 0}},
    )

    assert card["status"] == "Ready"
    assert card["task_version_id"] == "taskv_123"
    assert card["source_health"]["ok_count"] == 1
    assert card["last_run"]["has_output"] is True


def test_build_task_card_failed_no_output_and_config_changed_states():
    from insightbot.product import build_task_card

    failed = build_task_card(
        _task_spec(),
        {"is_runnable": True, "issues": [], "summary": {}},
        {"task_id": "daily", "ok": False, "error": "send failed", "final_markdown": "### A"},
        None,
        None,
    )
    no_output = build_task_card(
        _task_spec(),
        {"is_runnable": True, "issues": [], "summary": {}},
        {"task_id": "daily", "ok": True, "final_markdown": "", "selected_count": 0},
        None,
        None,
    )
    changed = build_task_card(
        _task_spec(),
        {"is_runnable": True, "needs_revalidation": True, "issues": [], "summary": {}},
        {"task_id": "daily", "ok": True, "final_markdown": "### A"},
        None,
        None,
    )

    assert failed["status"] == "Failed"
    assert no_output["status"] == "No Output"
    assert changed["status"] == "Config Changed"


def test_build_task_card_needs_review_without_latest_run():
    from insightbot.product import build_task_card

    card = build_task_card(
        _task_spec(),
        {"is_runnable": False, "issues": [{"severity": "error", "message": "missing channel"}], "summary": {}},
        None,
        None,
        None,
    )

    assert card["status"] == "Needs Review"
    assert card["last_run"] is None
    assert card["risk_summary"]["error_count"] == 1


def test_build_run_evidence_and_source_health_are_json_safe():
    from insightbot.product import build_run_evidence, build_source_health_summary

    evidence = build_run_evidence(
        {
            "run_id": "run_1",
            "task_id": "daily",
            "task_version_id": "taskv_123",
            "ok": True,
            "final_markdown": "A" * 1300,
            "run_trace": {
                "stages": [{"stage": "fetch", "input_count": 0, "output_count": 8, "warnings": [], "errors": []}]
            },
            "diagnosis": {"severity": "ok", "findings": []},
        }
    )
    health = build_source_health_summary(
        {
            "counts": {"total": 2, "ok": 1, "stale": 0, "error": 1},
            "categories": [
                {
                    "category": "Marketing",
                    "feeds": [
                        {
                            "url": "https://example.com/feed.xml",
                            "status": "error",
                            "error_type": "timeout",
                            "error_message": "timed out",
                        }
                    ],
                }
            ],
        }
    )

    assert evidence["stage_counts"]["fetch"]["output"] == 8
    assert len(evidence["output_preview"]) == 1200
    assert health["error_count"] == 1
    assert "api_key" not in str(health)


def test_build_workspace_state_uses_shared_task_cards():
    from insightbot.product import build_workspace_state

    workspace = build_workspace_state(
        {"daily": _task_spec().raw},
        "daily",
        {"daily": {"validation": {"is_runnable": True, "issues": [], "summary": {}}}},
        {},
    )

    assert workspace["selected_task_id"] == "daily"
    assert workspace["active_count"] == 1
    assert workspace["task_cards"][0]["task_id"] == "daily"
    assert workspace["selected_task_card"]["task_id"] == "daily"
    assert workspace["human_diagnosis"]["next_action"]


def test_build_workspace_state_reports_no_output_diagnosis():
    from insightbot.product import build_workspace_state

    workspace = build_workspace_state(
        {"daily": _task_spec().raw},
        "daily",
        {
            "daily": {
                "validation": {"is_runnable": True, "issues": [], "summary": {}},
                "latest_run": {"task_id": "daily", "ok": True, "final_markdown": "", "selected_count": 0},
            }
        },
        {"daily": {"counts": {"total": 1, "ok": 1, "stale": 0, "error": 0}}},
    )

    assert workspace["selected_task_card"]["status"] == "No Output"
    assert workspace["human_diagnosis"]["severity"] == "warning"
    assert "没有产出" in workspace["human_diagnosis"]["message"]


def test_build_change_proposal_flags_stale_base_version():
    from insightbot.product import build_change_proposal

    proposal = build_change_proposal(
        {
            "changeset_id": "chg_1",
            "task_id": "daily",
            "intent": "Rename task",
            "risk_level": "low",
            "base_version_id": "taskv_old",
            "target_version_id": "taskv_new",
            "operations": [
                {"op": "replace", "path": "/name", "before": "Daily", "after": "Daily Updated"},
                {"op": "replace", "path": "/ai/api_key", "before": "secret", "after": "new", "sensitive": True},
            ],
        },
        current_version_id="taskv_current",
    )

    assert proposal["is_stale"] is True
    assert proposal["approval_required"] is True
    assert proposal["operation_count"] == 2
    assert "<redacted>" in proposal["human_readable_diff"][1]


def test_build_change_proposal_redacts_sensitive_paths_without_flag():
    from insightbot.product import build_change_proposal

    proposal = build_change_proposal(
        {
            "changeset_id": "chg_2",
            "task_id": "daily",
            "operations": [
                {"op": "replace", "path": "/channels/wecom_main/secret", "before": "old-secret", "after": "new-secret"},
                {"op": "replace", "path": "/channels/feishu/webhook_url", "before": "https://old", "after": "https://new"},
            ],
        }
    )

    assert "old-secret" not in str(proposal)
    assert "new-secret" not in str(proposal)
    assert "https://old" not in str(proposal)
    assert "https://new" not in str(proposal)
    assert proposal["human_readable_diff"].count("replace /channels/wecom_main/secret: '<redacted>' -> '<redacted>'") == 1


def test_build_workspace_state_keeps_bad_task_as_needs_review_card():
    from insightbot.product import build_workspace_state

    workspace = build_workspace_state(
        {
            "daily": _task_spec().raw,
            "broken": ["not", "a", "task"],
        },
        "broken",
        {"daily": {"validation": {"is_runnable": True, "issues": [], "summary": {}}}},
        {},
    )

    broken_card = next(card for card in workspace["task_cards"] if card["task_id"] == "broken")
    assert broken_card["status"] == "Needs Review"
    assert broken_card["risk_summary"]["error_count"] == 1
    assert workspace["selected_task_id"] == "broken"
