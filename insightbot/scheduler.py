"""
Multi-task scheduler with built-in run loop.

Each task has its own schedule (hour/minute/day_of_week), feeds, pipeline,
and list of target channels. The scheduler runs in the main process,
checking every minute whether any enabled task should fire.
"""

import logging
import os
import time
from datetime import datetime
from typing import Callable

from .channels import init_channels
from .config import load_channels, load_tasks, load_tasks_config, normalize_task_definition
from .logging_setup import build_logger
from .paths import bot_log_file_path, channels_file_path, default_bot_dir, tasks_file_path

logger = logging.getLogger("Scheduler")


class Task:
    """
    Represents a single scheduled task definition.
    Knows how to check its schedule and how to run itself.
    """

    def __init__(
        self,
        task_id: str,
        task_def: dict,
        config_loader_fn: Callable[[], dict],
    ):
        self.task_id = task_id
        self.name = task_def.get("name", task_id)
        self.enabled = task_def.get("enabled", False)
        self.channels = task_def.get("channels", [])
        self.schedule = task_def.get("schedule", {})
        self.pipeline = task_def.get("pipeline", "editorial")
        normalized = normalize_task_definition(task_def)
        self.sources = normalized.get("sources", {})
        self.sections = normalized.get("sections", {})
        self.feeds = normalized.get("feeds", {})
        self.pipeline_config = task_def.get("pipeline_config", {})
        self.search = self.sources.get("search", {})
        self._config_loader = config_loader_fn
        self._last_run_at: datetime | None = None

    def should_run_now(self) -> bool:
        """
        Check if current time matches this task's schedule.
        Includes idempotency guard: skips if already fired within last 70 seconds.
        """
        if not self.enabled:
            return False

        now = datetime.now()
        sched = self.schedule

        # Hour check
        if "hour" in sched and now.hour != sched["hour"]:
            return False

        # Minute check
        if "minute" in sched and now.minute != sched["minute"]:
            return False

        # day_of_week check (0=Monday, 6=Sunday)
        if "day_of_week" in sched:
            if now.weekday() != sched["day_of_week"]:
                return False

        # Idempotency guard
        if self._last_run_at is not None:
            elapsed = (now - self._last_run_at).total_seconds()
            if elapsed < 70:
                return False

        return True

    def run(self, dry_run: bool = False) -> dict:
        """Run this task via task_runner."""
        from .task_runner import run_task

        self._last_run_at = datetime.now()
        return run_task(
            self.task_id,
            self._config_loader,
            dry_run=dry_run,
        )


class Scheduler:
    """
    Manages all tasks and the scheduler loop.
    """

    def __init__(self, bot_dir: str | None = None):
        self.bot_dir = bot_dir or default_bot_dir()
        self.tasks: dict[str, Task] = {}
        self._log = logging.getLogger("Scheduler")
        self._runtime_mtimes: dict[str, float | None] = {}
        self._load_tasks()
        self._refresh_runtime_mtimes()

    def _make_task_config_loader(self, task_id: str) -> Callable[[], dict]:
        """Build a per-task config loader so CLI/systemd runs use the full task config."""
        return lambda: load_tasks_config(task_id, self.bot_dir)

    def _load_tasks(self) -> None:
        """Load tasks from tasks.json."""
        tasks_data = load_tasks(self.bot_dir)
        self.tasks.clear()
        for task_id, task_def in tasks_data.get("tasks", {}).items():
            self.tasks[task_id] = Task(
                task_id,
                task_def,
                self._make_task_config_loader(task_id),
            )
        self._log.info(f"Loaded {len(self.tasks)} tasks from tasks.json")

    def _watched_runtime_files(self) -> dict[str, str]:
        bot_dir = getattr(self, "bot_dir", None) or default_bot_dir()
        return {
            "tasks": tasks_file_path(bot_dir),
            "channels": channels_file_path(bot_dir),
        }

    def _get_runtime_mtimes(self) -> dict[str, float | None]:
        mtimes: dict[str, float | None] = {}
        for key, path in self._watched_runtime_files().items():
            try:
                mtimes[key] = os.path.getmtime(path)
            except OSError:
                mtimes[key] = None
        return mtimes

    def _refresh_runtime_mtimes(self) -> None:
        self._runtime_mtimes = self._get_runtime_mtimes()

    def reload_if_config_changed(self) -> bool:
        """Reload tasks and channels if runtime config files changed on disk."""
        current = self._get_runtime_mtimes()
        if current == getattr(self, "_runtime_mtimes", current):
            return False
        self._log.info("Runtime config changed on disk; reloading scheduler state.")
        self._load_tasks()
        init_channels(load_channels(self.bot_dir))
        self._runtime_mtimes = current
        return True

    def reload(self) -> None:
        """Reload tasks.json from disk."""
        self._load_tasks()
        self._refresh_runtime_mtimes()
        self._log.info("Scheduler tasks reloaded.")

    def run_task_by_id(self, task_id: str, dry_run: bool = False) -> dict:
        """Run a specific task by ID immediately (bypasses schedule)."""
        self.reload_if_config_changed()
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found.")
        self._log.info(f"Running task '{task_id}' (dry_run={dry_run})")
        return task.run(dry_run=dry_run)

    def run_all_enabled(self, dry_run: bool = False) -> list[dict]:
        """Run all enabled tasks immediately."""
        results = []
        self.reload_if_config_changed()
        for task in self.tasks.values():
            if task.enabled:
                try:
                    result = task.run(dry_run=dry_run)
                    results.append({"task_id": task.task_id, "ok": result.get("ok", False)})
                except Exception as e:
                    self._log.error(f"Task '{task.task_id}' failed: {e}")
                    results.append({"task_id": task.task_id, "ok": False, "error": str(e)})
        return results

    def run_loop(self, check_interval_seconds: int = 60) -> None:
        """
        Start the scheduler loop in the foreground.
        This method blocks the current process until interrupted.
        """
        self._log.info(
            f"Scheduler loop started. Watching {len(self.tasks)} tasks, "
            f"checking every {check_interval_seconds}s."
        )
        while True:
            self.reload_if_config_changed()
            for task in self.tasks.values():
                if task.enabled and task.should_run_now():
                    try:
                        self._log.info(f"Firing scheduled task: {task.task_id}")
                        task.run(dry_run=False)
                    except Exception as e:
                        self._log.error(f"Scheduled task '{task.task_id}' failed: {e}")
            time.sleep(check_interval_seconds)


def create_scheduler(bot_dir: str | None = None) -> Scheduler:
    """
    Factory that creates a Scheduler and triggers auto-migration if needed.
    """
    bot_dir = bot_dir or default_bot_dir()

    # Auto-migrate if tasks.json doesn't exist
    if not os.path.exists(tasks_file_path(bot_dir)):
        from .migrate import migrate_from_v1
        migrate_from_v1(bot_dir)

    scheduler = Scheduler(bot_dir)
    return scheduler
