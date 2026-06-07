"""
test_scheduler.py — insightbot.scheduler 核心逻辑测试

测试范围：
  - Task.should_run_now() 时间匹配和 idempotency guard
  - Scheduler.run_all_enabled() 只运行 enabled 任务
  - Scheduler.reload() 重新加载 tasks.json
"""

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
