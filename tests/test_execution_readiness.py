from __future__ import annotations

from scripts.ui.dry_run import analyze_task_execution_readiness


def test_readiness_predicts_run_send_and_archive() -> None:
    selected_task = {
        "name": "Daily Brief",
        "enabled": True,
        "schedule": {"hour": 8, "minute": 0},
        "channels": [
            {"channel_id": "ch_wecom", "audience": "ops", "purpose": "brief"},
            "ch_archive",
        ],
    }
    channels_data = {
        "channels": {
            "ch_wecom": {
                "type": "wecom",
                "name": "企业微信",
                "cid": "cid",
                "secret": "secret",
                "agent_id": "agent",
            },
            "ch_archive": {
                "type": "web_archive",
                "name": "任务归档",
                "public_name": "brief",
            },
        }
    }
    task_validation = {"is_runnable": True, "issues": []}
    task_state = {"needs_revalidation": False, "config_revision": "rev1"}

    readiness = analyze_task_execution_readiness(
        selected_task_id="daily_brief",
        selected_task=selected_task,
        task_validation=task_validation,
        task_state=task_state,
        channels_data=channels_data,
        health_snapshot={"checked_at": "2026-06-03T10:00:00"},
        latest_run_record={"ok": True, "started_at": "2026-06-03T08:00:00"},
        latest_success_record={"started_at": "2026-06-03T08:00:00"},
        run_summary={"overall_no_push": True, "categories": {"a": {"status": "ok"}}, "runtime_errors": []},
    )
    assert readiness["can_run"] is True
    assert readiness["can_send"] is True
    assert readiness["can_archive"] is True
    assert readiness["run_status_hint"].startswith("当前配置满足")
    assert readiness["send_hint"].startswith("至少有一个可执行发送频道")
    assert readiness["archive_hint"].startswith("存在可用 web_archive")
    assert readiness["health_reason"] == "已有健康快照"
    assert readiness["can_archive"] is True
    assert "无推送" in readiness["no_push_hint"]


def test_readiness_blocks_task_when_not_enabled() -> None:
    selected_task = {
        "name": "Draft",
        "enabled": False,
        "schedule": {"hour": 8, "minute": 0},
        "channels": ["ch_wecom"],
    }
    channels_data = {"channels": {"ch_wecom": {"type": "wecom", "name": "WX", "cid": "cid", "secret": "secret", "agent_id": "agent"}}}
    task_validation = {"is_runnable": True, "issues": []}
    task_state = {"needs_revalidation": False}

    readiness = analyze_task_execution_readiness(
        selected_task_id="draft",
        selected_task=selected_task,
        task_validation=task_validation,
        task_state=task_state,
        channels_data=channels_data,
        latest_dry_run={"ok": False, "error": "sample"},
    )
    assert readiness["can_run"] is False
    assert readiness["can_send"] is False
    assert readiness["can_archive"] is False
    assert "任务未启用" in readiness["run_status_hint"]
    assert readiness["dry_run_status"] == "Dry Run 失败：sample"


def test_readiness_warns_when_channel_not_ready() -> None:
    selected_task = {
        "name": "Missing Channel",
        "enabled": True,
        "schedule": {"hour": 8, "minute": 0},
        "channels": ["ch_wecom"],
    }
    channels_data = {
        "channels": {
            "ch_wecom": {
                "type": "wecom",
                "name": "WX",
                # intentionally missing cid/secret/agent_id
            }
        }
    }
    task_validation = {"is_runnable": True, "issues": []}
    task_state = {"needs_revalidation": False}

    readiness = analyze_task_execution_readiness(
        selected_task_id="missing",
        selected_task=selected_task,
        task_validation=task_validation,
        task_state=task_state,
        channels_data=channels_data,
        health_snapshot=None,
    )
    assert readiness["can_run"] is True
    assert readiness["can_send"] is False
    assert readiness["can_archive"] is False
    assert readiness["send_hint"].startswith("发送频道存在但当前配置不完整")
    assert readiness["health_reason"].startswith("尚未刷新 RSS")


def test_readiness_ignores_disabled_channel_routes() -> None:
    selected_task = {
        "name": "Disabled route",
        "enabled": True,
        "schedule": {"hour": 8, "minute": 0},
        "channels": [
            {
                "channel_id": "ch_wecom",
                "audience": "ops",
                "purpose": "brief",
                "enabled": False,
            }
        ],
    }
    channels_data = {
        "channels": {
            "ch_wecom": {
                "type": "wecom",
                "name": "企业微信",
                "cid": "cid",
                "secret": "secret",
                "agent_id": "agent",
            }
        }
    }
    task_validation = {"is_runnable": True, "issues": []}
    task_state = {"needs_revalidation": False, "config_revision": "rev1"}

    readiness = analyze_task_execution_readiness(
        selected_task_id="disabled_route",
        selected_task=selected_task,
        task_validation=task_validation,
        task_state=task_state,
        channels_data=channels_data,
    )
    assert readiness["can_send"] is False
    assert readiness["can_archive"] is False
    assert readiness["send_hint"].startswith("未配置任何发送/归档路由")
