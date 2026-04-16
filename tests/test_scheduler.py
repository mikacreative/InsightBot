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
            # Simulate first run by calling run() which sets _last_run_at
            with patch("insightbot.scheduler.Task.run") as mock_run:
                mock_run.return_value = {}
                task.run()
            # Second check within 70s — should be blocked by idempotency
            mock_dt.now.return_value = datetime(2026, 4, 16, 8, 1)
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
            sched._config_loader_fn = FakeConfigLoader()

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
