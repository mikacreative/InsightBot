"""
test_scheduler.py — insightbot.scheduler 核心逻辑测试

测试范围：
  - Task.should_run_now() 时间匹配和 idempotency guard
  - Scheduler.run_all_enabled() 只运行 enabled 任务
  - Scheduler.reload() 重新加载 tasks.json
  - tasks.json 损坏时的容错(保留旧状态 + config_error + 自动恢复)
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class FakeConfigLoader:
    def __init__(self, cfg=None):
        self._cfg = cfg or {}

    def __call__(self):
        return self._cfg.copy()


class TestTaskShouldRunNow:
    """Task.should_run_now() 的时间匹配和 idempotency 测试"""

    def test_enabled_task_fires_when_hour_minute_match(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": True,
            "schedule": {"hour": 8, "minute": 0},
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert task.should_run_now() is True

    def test_disabled_task_never_fires(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": False,
            "schedule": {"hour": 8, "minute": 0},
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert task.should_run_now() is False

    def test_hour_mismatch(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": True,
            "schedule": {"hour": 9, "minute": 0},
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert task.should_run_now() is False

    def test_minute_mismatch(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": True,
            "schedule": {"hour": 8, "minute": 30},
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert task.should_run_now() is False

    def test_day_of_week_mismatch(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": True,
            "schedule": {"hour": 8, "minute": 0, "day_of_week": 0},  # Monday
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        # Thursday (weekday=3)
        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert task.should_run_now() is False

    def test_idempotency_guard_blocks_double_fire(self):
        from insightbot.scheduler import Task
        task_def = {
            "enabled": True,
            "schedule": {"hour": 8, "minute": 0},
            "name": "Test",
        }
        task = Task("t1", task_def, FakeConfigLoader())

        with patch("insightbot.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # First fire — should run
            assert task.should_run_now() is True
            # Simulate the scheduler marking this task as already fired.
            task._last_run_at = datetime(2026, 4, 16, 8, 0)
            # Second check within 70s — should be blocked by idempotency
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 0, 30)
            assert task.should_run_now() is False


class TestSchedulerRunAllEnabled:
    def test_only_enabled_tasks_run(self):
        from insightbot.scheduler import Scheduler

        with patch("insightbot.scheduler.load_tasks") as mock_load:
            mock_load.return_value = {
                "tasks": {
                    "task_a": {"enabled": True, "name": "A", "schedule": {"hour": 8, "minute": 0}},
                    "task_b": {"enabled": False, "name": "B", "schedule": {"hour": 8, "minute": 0}},
                }
            }
            with patch.object(Scheduler, "_load_tasks"):
                sched = Scheduler.__new__(Scheduler)
                sched.tasks = {}
                sched._log = MagicMock()
                from insightbot.scheduler import Task
                sched.tasks = {
                    "task_a": Task("task_a", {"enabled": True, "name": "A", "schedule": {"hour": 8, "minute": 0}}, FakeConfigLoader()),
                    "task_b": Task("task_b", {"enabled": False, "name": "B", "schedule": {"hour": 8, "minute": 0}}, FakeConfigLoader()),
                }

                with patch.object(Scheduler, "run_task_by_id") as mock_run:
                    mock_run.return_value = {"ok": True}
                    results = sched.run_all_enabled()

                assert len(results) == 1
                assert results[0]["task_id"] == "task_a"


class TestSchedulerConfigErrorTolerance:
    """tasks.json 损坏(如手改少逗号)时不得拖垮调度器/控制台。"""

    def _bare_scheduler(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp"
        sched.tasks = {}
        sched._log = MagicMock()
        sched.config_error = None
        return sched

    def test_broken_tasks_json_keeps_previous_state(self):
        sched = self._bare_scheduler()
        sched.tasks = {"existing": MagicMock()}

        with patch(
            "insightbot.scheduler.load_tasks",
            side_effect=json.JSONDecodeError("Expecting ',' delimiter", "doc", 143),
        ):
            sched._load_tasks()

        assert "existing" in sched.tasks  # 保留修复前状态
        assert sched.config_error is not None
        assert "JSONDecodeError" in sched.config_error

    def test_recovery_clears_error(self):
        sched = self._bare_scheduler()
        sched.config_error = "JSONDecodeError: previous"

        with patch("insightbot.scheduler.load_tasks", return_value={"tasks": {}}):
            sched._load_tasks()

        assert sched.config_error is None

    def test_broken_channels_json_does_not_kill_reload(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp"
        sched.tasks = {}
        sched._log = MagicMock()
        sched.config_error = None
        sched._runtime_mtimes = {"tasks": 1.0, "channels": 1.0}

        with patch.object(Scheduler, "_get_runtime_mtimes", return_value={"tasks": 1.0, "channels": 2.0}), \
             patch.object(Scheduler, "_load_tasks"), \
             patch("insightbot.scheduler.load_channels", side_effect=json.JSONDecodeError("bad", "doc", 1)):
            changed = sched.reload_if_config_changed()

        assert changed is True  # reload 本身不抛异常

    def test_config_loader_falls_back_to_last_good_snapshot(self):
        sched = self._bare_scheduler()
        loader = sched._make_task_config_loader("t1")

        with patch("insightbot.scheduler.load_tasks_config", return_value={"_task": 1}):
            assert loader() == {"_task": 1}
        with patch(
            "insightbot.scheduler.load_tasks_config",
            side_effect=json.JSONDecodeError("Expecting ',' delimiter", "doc", 143),
        ):
            assert loader() == {"_task": 1}  # 文件损坏期仍按最近良好快照运行

    def test_config_loader_reraises_without_any_snapshot(self):
        sched = self._bare_scheduler()
        loader = sched._make_task_config_loader("t1")

        with patch(
            "insightbot.scheduler.load_tasks_config",
            side_effect=json.JSONDecodeError("bad", "doc", 1),
        ):
            with pytest.raises(json.JSONDecodeError):
                loader()

    def test_tool_manifest_uses_retained_tasks_when_file_broken(self):
        sched = self._bare_scheduler()
        task = MagicMock()
        task.task_def = {"name": "X"}
        sched.tasks = {"task_x": task}

        with patch("insightbot.scheduler.load_tasks", side_effect=json.JSONDecodeError("bad", "doc", 1)):
            manifest = sched.get_tool_manifest_command()

        assert manifest["runtime"]["task_ids"] == ["task_x"]


class TestSchedulerReload:
    def test_reload_refreshes_tasks(self):
        from insightbot.scheduler import Scheduler

        with patch("insightbot.scheduler.load_tasks") as mock_load:
            mock_load.return_value = {
                "tasks": {
                    "task_x": {"enabled": True, "name": "X", "schedule": {"hour": 8, "minute": 0}},
                }
            }
            sched = Scheduler.__new__(Scheduler)
            sched.bot_dir = "/tmp"
            sched.tasks = {}
            sched._log = MagicMock()

            sched._load_tasks()
            assert "task_x" in sched.tasks

            mock_load.return_value = {
                "tasks": {
                    "task_y": {"enabled": True, "name": "Y", "schedule": {"hour": 9, "minute": 0}},
                }
            }
            sched.reload()
            assert "task_y" in sched.tasks
            assert "task_x" not in sched.tasks

    def test_reload_if_config_changed_refreshes_tasks_and_channels(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp"
        sched.tasks = {}
        sched._log = MagicMock()
        sched._runtime_mtimes = {"tasks": 1.0, "channels": 1.0}

        with patch.object(Scheduler, "_get_runtime_mtimes", return_value={"tasks": 2.0, "channels": 1.0}), \
             patch.object(Scheduler, "_load_tasks") as mock_load_tasks, \
             patch("insightbot.scheduler.load_channels", return_value={"channels": {}}) as mock_load_channels, \
             patch("insightbot.scheduler.init_channels") as mock_init_channels:
            changed = sched.reload_if_config_changed()

        assert changed is True
        mock_load_tasks.assert_called_once()
        mock_load_channels.assert_called_once_with("/tmp")
        mock_init_channels.assert_called_once_with({"channels": {}})
        assert sched._runtime_mtimes == {"tasks": 2.0, "channels": 1.0}


class TestSchedulerTaskConfigLoading:
    def test_loads_full_task_config_per_task(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        loader = sched._make_task_config_loader("daily_brief")

        with patch("insightbot.scheduler.load_tasks_config") as mock_load_task_config:
            mock_load_task_config.return_value = {"feeds": {"A": {}}, "_task_name": "Daily"}
            result = loader()

        mock_load_task_config.assert_called_once_with("daily_brief", "/tmp/insightbot")
        assert result == {"feeds": {"A": {}}, "_task_name": "Daily"}

    def test_task_config_loader_attaches_task_version_when_tasks_are_available(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched._log = MagicMock()
        loader = sched._make_task_config_loader("daily_brief")
        task_def = {
            "name": "Daily",
            "enabled": True,
            "pipeline": "editorial",
            "sections": {"Marketing": {"prompt": "Keep marketing news."}},
            "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
            "channels": ["wecom_main"],
            "schedule": {"hour": 8, "minute": 0},
        }

        with patch("insightbot.scheduler.load_tasks_config", return_value={"feeds": {}, "_task_name": "Daily"}), \
             patch("insightbot.scheduler.load_tasks", return_value={"tasks": {"daily_brief": task_def}}):
            result = loader()

        assert result["_task_version_id"].startswith("taskv_")


class TestSchedulerDomainCommands:
    def test_create_and_delete_task_commands_save_and_reload(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        new_task = {**tasks_payload["tasks"]["daily"], "name": "Weekly", "schedule": {"hour": 9, "minute": 0}}

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.save_tasks") as mock_save, \
             patch.object(Scheduler, "reload") as mock_reload:
            create_result = sched.create_task_command(
                "weekly",
                new_task,
                intent="Create weekly task",
                rationale="Need weekly reporting.",
            )

        assert create_result.ok is True
        assert create_result.command == "create_task"
        assert create_result.updated_tasks["tasks"]["weekly"]["name"] == "Weekly"
        mock_save.assert_called_once_with(create_result.updated_tasks, "/tmp/insightbot")
        mock_reload.assert_called_once()

        with patch("insightbot.scheduler.load_tasks", return_value=create_result.updated_tasks), \
             patch("insightbot.scheduler.save_tasks") as mock_save, \
             patch.object(Scheduler, "reload") as mock_reload:
            delete_result = sched.delete_task_command(
                "weekly",
                intent="Delete weekly task",
                rationale="Cleanup test task.",
            )

        assert delete_result.ok is True
        assert delete_result.command == "delete_task"
        assert "weekly" not in delete_result.updated_tasks["tasks"]
        mock_save.assert_called_once_with(delete_result.updated_tasks, "/tmp/insightbot")
        mock_reload.assert_called_once()

    def test_validate_task_command_uses_domain_validation_with_channels(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": ""}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["missing_channel"],
                    "schedule": {},
                }
            }
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.load_channels", return_value={"channels": {"wecom_main": {}}}):
            result = sched.validate_task_command("daily")

        assert result["is_runnable"] is False
        assert result["status"] == "not_ready"
        codes = {issue["code"] for issue in result["issues"]}
        assert "channel_not_found" in codes
        assert "missing_schedule" in codes
        assert "missing_section_prompt" in codes
        assert result["domain_diagnosis"]["severity"] == "error"

    def test_tool_manifest_command_includes_runtime_task_ids(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {"name": "Daily"},
                "weekly": {"name": "Weekly"},
            }
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload):
            manifest = sched.get_tool_manifest_command()

        tools = {tool["name"] for tool in manifest["tools"]}
        assert {"validate_task", "dry_run_task", "run_task", "apply_changeset"} <= tools
        assert manifest["runtime"]["bot_dir"] == "/tmp/insightbot"
        assert manifest["runtime"]["task_ids"] == ["daily", "weekly"]

    def test_execute_tool_call_enforces_approval_and_routes_read_tools(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()
        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.load_channels", return_value={"channels": {"wecom_main": {}}}):
            list_result = sched.execute_tool_call("list_tasks", {})
            spec_result = sched.execute_tool_call("get_task_spec", {"task_id": "daily"})
            missing_args = sched.execute_tool_call("get_task_spec", {})
            extra_args = sched.execute_tool_call("get_task_spec", {"task_id": "daily", "extra": True})
            unsafe_id = sched.execute_tool_call("get_task_spec", {"task_id": "../bad"})
            blocked_run = sched.execute_tool_call("run_task", {"task_id": "daily"})

        assert list_result["ok"] is True
        assert list_result["output"]["task_ids"] == ["daily"]
        assert spec_result["ok"] is True
        assert spec_result["output"]["task_id"] == "daily"
        assert missing_args["ok"] is False
        assert missing_args["error"] == "invalid_arguments"
        assert extra_args["ok"] is False
        assert extra_args["error"] == "invalid_arguments"
        assert unsafe_id["ok"] is False
        assert "task_id" in unsafe_id["details"][0]
        assert blocked_run["ok"] is False
        assert blocked_run["error"] == "Tool requires approval."

    def test_execute_tool_call_returns_product_read_models(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()
        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {
                        "rss": [
                            {
                                "id": "src",
                                "url": "https://example.com/feed.xml",
                                "enabled": True,
                                "api_key": "should-not-leak",
                            }
                        ]
                    },
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        latest_run = {
            "run_id": "run_1",
            "task_id": "daily",
            "ok": True,
            "dry_run": True,
            "final_markdown": "### A\n> summary",
            "channel_results": [],
            "run_trace": {
                "stages": [
                    {"stage": "fetch", "input_count": 0, "output_count": 3, "warnings": [], "errors": []}
                ]
            },
            "diagnosis": {"severity": "ok", "findings": []},
        }
        health = {
            "counts": {"total": 2, "ok": 1, "stale": 0, "error": 1},
            "categories": [
                {
                    "category": "Marketing",
                    "feeds": [
                        {
                            "name": "Example Feed",
                            "url": "https://example.com/feed.xml",
                            "status": "error",
                            "error_type": "timeout",
                            "error_message": "timed out",
                        }
                    ],
                }
            ],
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.load_channels", return_value={"channels": {"wecom_main": {}}}), \
             patch("insightbot.run_history.get_latest_run", return_value=latest_run), \
             patch("insightbot.run_history.get_latest_successful_send", return_value=None), \
             patch("insightbot.task_health_store.load_task_health", return_value=health):
            cards = sched.execute_tool_call("list_task_cards", {})
            workspace = sched.execute_tool_call("get_workspace_state", {"selected_task_id": "daily"})
            status = sched.execute_tool_call("get_task_status", {"task_id": "daily"})
            evidence = sched.execute_tool_call("get_latest_run_evidence", {"task_id": "daily"})
            source_health = sched.execute_tool_call("get_source_health_summary", {"task_id": "daily"})
            bad_args = sched.execute_tool_call("get_task_status", {"task_id": "daily", "raw_config": True})
            bad_workspace_args = sched.execute_tool_call("get_workspace_state", {"selected_task_id": "../bad"})

        assert cards["ok"] is True
        assert cards["output"]["task_cards"][0]["task_id"] == "daily"
        assert workspace["ok"] is True
        assert workspace["output"]["selected_task_id"] == "daily"
        assert workspace["output"]["selected_task_card"]["task_id"] == "daily"
        assert status["output"]["status"] == "Ready"
        assert evidence["output"]["stage_counts"]["fetch"]["output"] == 3
        assert source_health["output"]["error_count"] == 1
        assert "should-not-leak" not in str(cards)
        assert "should-not-leak" not in str(status)
        assert bad_args["ok"] is False
        assert bad_args["error"] == "invalid_arguments"
        assert bad_workspace_args["ok"] is False

    def test_product_read_models_degrade_when_one_task_validation_fails(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()
        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                },
                "broken": ["not", "a", "task"],
            }
        }

        def validate_side_effect(task_id: str):
            if task_id == "broken":
                raise ValueError("bad task")
            return {"is_runnable": True, "issues": [], "summary": {"task_version_id": "taskv_daily"}}

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.run_history.get_latest_run", return_value=None), \
             patch("insightbot.run_history.get_latest_successful_send", return_value=None), \
             patch("insightbot.task_health_store.load_task_health", return_value=None), \
             patch.object(Scheduler, "validate_task_command", side_effect=validate_side_effect):
            result = sched.execute_tool_call("list_task_cards", {})

        assert result["ok"] is True
        by_id = {card["task_id"]: card for card in result["output"]["task_cards"]}
        assert by_id["daily"]["status"] == "Ready"
        assert by_id["broken"]["status"] == "Needs Review"
        assert by_id["broken"]["risk_summary"]["error_count"] == 1

    def test_execute_tool_call_can_apply_changeset_when_approved(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()
        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        target_task = {**tasks_payload["tasks"]["daily"], "name": "Daily Updated"}

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload):
            proposal = sched.execute_tool_call(
                "propose_task_changeset",
                {
                    "task_id": "daily",
                    "target_task_definition": target_task,
                    "intent": "Rename task",
                },
            )

        assert proposal["ok"] is True
        changeset = proposal["output"]

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.save_tasks") as mock_save, \
             patch.object(Scheduler, "reload") as mock_reload:
            blocked_apply = sched.execute_tool_call("apply_changeset", {"changeset": changeset})
            apply_result = sched.execute_tool_call("apply_changeset", {"changeset": changeset}, approved=True)

        assert blocked_apply["ok"] is False
        assert apply_result["ok"] is True
        assert apply_result["output"]["tasks"]["daily"]["name"] == "Daily Updated"
        mock_save.assert_called_once()
        mock_reload.assert_called_once()

    def test_execute_tool_call_supports_product_changeset_aliases(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()
        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        target_task = {**tasks_payload["tasks"]["daily"], "name": "Daily Updated"}

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload):
            proposal = sched.execute_tool_call(
                "propose_task_update",
                {
                    "task_id": "daily",
                    "target_task_definition": target_task,
                    "intent": "Rename task",
                },
            )

        assert proposal["ok"] is True
        changeset = proposal["output"]

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.save_tasks") as mock_save, \
             patch.object(Scheduler, "reload") as mock_reload:
            blocked_apply = sched.execute_tool_call("approve_and_apply_changeset", {"changeset": changeset})
            apply_result = sched.execute_tool_call(
                "approve_and_apply_changeset",
                {"changeset": changeset},
                approved=True,
            )

        assert blocked_apply["ok"] is False
        assert apply_result["ok"] is True
        assert apply_result["output"]["tasks"]["daily"]["name"] == "Daily Updated"
        mock_save.assert_called_once()
        mock_reload.assert_called_once()

    def test_changeset_commands_propose_without_write_and_apply_with_save(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        target_task = {
            **tasks_payload["tasks"]["daily"],
            "name": "Daily Updated",
            "channels": ["wecom_main", "wecom_backup"],
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.save_tasks") as mock_save:
            changeset = sched.propose_task_changeset_command(
                "daily",
                target_task,
                intent="Add backup channel",
                rationale="Improve delivery resilience.",
            )

        mock_save.assert_not_called()
        assert changeset.task_id == "daily"
        assert changeset.operations
        assert changeset.target_version_id != changeset.base_version_id

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch("insightbot.scheduler.save_tasks") as mock_save, \
             patch.object(Scheduler, "reload") as mock_reload:
            updated = sched.apply_changeset_command(changeset)

        assert updated["tasks"]["daily"]["name"] == "Daily Updated"
        mock_save.assert_called_once_with(updated, "/tmp/insightbot")
        mock_reload.assert_called_once()

    def test_dry_run_task_command_wraps_existing_run_with_domain_metadata(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {
                        "rss": [
                            {
                                "id": "src",
                                "url": "https://example.com/feed.xml",
                                "enabled": True,
                                "section_hints": ["Marketing"],
                            }
                        ]
                    },
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }

        run_payload = {
            "ok": True,
            "task_id": "daily",
            "pipeline": "editorial",
            "dry_run": True,
            "stage_results": {
                "global_candidates": [{"id": "c1"}],
                "screened_result": {"screened": [{"id": "c1"}]},
                "assignment_result": {"category_candidate_map": {"Marketing": [{"id": "c1"}]}, "unassigned": []},
                "category_results": {"Marketing": {"selected_items": [{"title": "A"}]}},
            },
            "channel_results": [],
            "final_markdown": "### A\n> summary",
            "error": None,
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch.object(Scheduler, "run_task_by_id", return_value=run_payload) as mock_run:
            result = sched.dry_run_task_command("daily")

        mock_run.assert_called_once_with("daily", dry_run=True)
        assert result.command == "dry_run_task"
        assert result.ok is True
        assert result.task_spec.task_id == "daily"
        assert result.task_version.version_id.startswith("taskv_")
        assert result.run_trace.task_version_id == result.task_version.version_id
        assert result.diagnosis.severity == "ok"

    def test_run_task_command_wraps_manual_run_with_domain_metadata(self):
        from insightbot.scheduler import Scheduler

        sched = Scheduler.__new__(Scheduler)
        sched.bot_dir = "/tmp/insightbot"
        sched.tasks = {}
        sched._log = MagicMock()

        tasks_payload = {
            "tasks": {
                "daily": {
                    "name": "Daily",
                    "enabled": True,
                    "pipeline": "editorial",
                    "sections": {"Marketing": {"prompt": "Keep marketing news."}},
                    "sources": {"rss": [{"id": "src", "url": "https://example.com/feed.xml", "enabled": True}]},
                    "channels": ["wecom_main"],
                    "schedule": {"hour": 8, "minute": 0},
                }
            }
        }
        run_payload = {
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
            "error": None,
        }

        with patch("insightbot.scheduler.load_tasks", return_value=tasks_payload), \
             patch.object(Scheduler, "run_task_by_id", return_value=run_payload) as mock_run:
            result = sched.run_task_command("daily")

        mock_run.assert_called_once_with("daily", dry_run=False)
        assert result.command == "run_task"
        assert result.ok is True
        assert result.run_trace.trigger_type == "manual"
        assert result.run_trace.stage("send").output_count == 1
        assert result.run_trace.task_version_id == result.task_version.version_id
