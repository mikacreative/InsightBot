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
from .config import load_channels, load_tasks, load_tasks_config, normalize_task_definition, save_tasks
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

    def run(self, dry_run: bool = False, trigger_type: str | None = None) -> dict:
        """Run this task via task_runner."""
        from .task_runner import run_task

        self._last_run_at = datetime.now()

        def load_config() -> dict:
            config = self._config_loader()
            if trigger_type:
                config["_task_trigger_type"] = trigger_type
            return config

        return run_task(
            self.task_id,
            load_config,
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
        def load_config() -> dict:
            config = load_tasks_config(task_id, self.bot_dir)
            try:
                from .domain import TaskVersion
                from .domain.commands import get_task_spec

                spec = get_task_spec(load_tasks(self.bot_dir), task_id)
                config["_task_version_id"] = TaskVersion.from_spec(spec).version_id
            except Exception as exc:
                getattr(self, "_log", logger).warning(
                    "Failed to attach TaskVersion for task '%s': %s",
                    task_id,
                    exc,
                )
            return config

        return load_config

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
        return task.run(dry_run=dry_run, trigger_type="dry_run" if dry_run else "manual")

    def validate_task_command(self, task_id: str) -> dict:
        """Validate a task through the Domain Kernel and return UI-compatible output."""
        from .domain import TaskVersion
        from .domain.commands import validate_task
        from .domain.compat import validation_result_from_domain

        tasks_payload = load_tasks(self.bot_dir)
        channels_payload = load_channels(self.bot_dir)
        spec, report = validate_task(
            tasks_payload,
            task_id,
            channels_payload=channels_payload,
        )
        result = validation_result_from_domain(spec, report)
        version = TaskVersion.from_spec(spec)
        result["summary"]["task_version_id"] = version.version_id
        result["task_version"] = version.to_dict()
        return result

    def get_tool_manifest_command(self) -> dict:
        """Expose the Domain Kernel tool manifest with current runtime task IDs."""
        from .domain import get_tool_manifest

        tasks_payload = load_tasks(self.bot_dir)
        manifest = get_tool_manifest()
        manifest["runtime"] = {
            "bot_dir": self.bot_dir,
            "task_ids": sorted(tasks_payload.get("tasks", {}).keys()),
        }
        return manifest

    def tool_manifest(self) -> dict:
        """Return the static Domain Kernel tool manifest."""
        from .domain import get_tool_manifest

        return get_tool_manifest()

    def execute_tool_call(self, tool_name: str, arguments: dict | None = None, *, approved: bool = False) -> dict:
        """
        Execute a Domain Kernel tool call through the same command boundary used by the UI.

        This is an internal Tool API adapter, not a network server. External MCP
        or Agent adapters should call this method instead of editing runtime
        config files or invoking Streamlit code.
        """
        from .domain import ChangeSet
        from .domain.commands import get_task_spec, get_task_version
        from .ids import require_safe_id

        args = arguments or {}
        tools = {tool["name"]: tool for tool in self.tool_manifest().get("tools", [])}
        tool = tools.get(tool_name)
        if tool is None:
            return {"ok": False, "tool": tool_name, "error": f"Unknown tool: {tool_name}"}
        validation_errors = self._validate_tool_arguments(tool.get("input_schema", {}), args)
        if validation_errors:
            return {
                "ok": False,
                "tool": tool_name,
                "error": "invalid_arguments",
                "details": validation_errors,
            }
        if tool.get("requires_approval") and not approved:
            return {
                "ok": False,
                "tool": tool_name,
                "requires_approval": True,
                "error": "Tool requires approval.",
            }

        try:
            tasks_payload = load_tasks(self.bot_dir)
            if tool_name == "list_tasks":
                tasks = tasks_payload.get("tasks", {}) or {}
                return {
                    "ok": True,
                    "tool": tool_name,
                    "output": {
                        "task_ids": sorted(tasks.keys()),
                        "tasks": [
                            {
                                "task_id": task_id,
                                "name": (task_def or {}).get("name", task_id) if isinstance(task_def, dict) else task_id,
                                "enabled": bool((task_def or {}).get("enabled", False)) if isinstance(task_def, dict) else False,
                            }
                            for task_id, task_def in sorted(tasks.items())
                        ],
                    },
                }
            if tool_name == "get_task_spec":
                task_id = require_safe_id(args.get("task_id"), label="task_id")
                return {
                    "ok": True,
                    "tool": tool_name,
                    "output": get_task_spec(tasks_payload, task_id).to_dict(),
                }
            if tool_name == "get_task_version":
                task_id = require_safe_id(args.get("task_id"), label="task_id")
                return {
                    "ok": True,
                    "tool": tool_name,
                    "output": get_task_version(tasks_payload, task_id).to_dict(),
                }
            if tool_name == "validate_task":
                return {"ok": True, "tool": tool_name, "output": self.validate_task_command(require_safe_id(args.get("task_id"), label="task_id"))}
            if tool_name == "dry_run_task":
                return {"ok": True, "tool": tool_name, "output": self.dry_run_task_command(require_safe_id(args.get("task_id"), label="task_id")).to_dict()}
            if tool_name == "run_task":
                return {"ok": True, "tool": tool_name, "output": self.run_task_command(require_safe_id(args.get("task_id"), label="task_id")).to_dict()}
            if tool_name == "propose_task_changeset":
                changeset = self.propose_task_changeset_command(
                    require_safe_id(args.get("task_id"), label="task_id"),
                    args.get("target_task_definition") or {},
                    intent=str(args.get("intent") or ""),
                    rationale=str(args.get("rationale") or ""),
                )
                return {"ok": True, "tool": tool_name, "output": changeset.to_dict()}
            if tool_name == "apply_changeset":
                changeset_payload = args.get("changeset") or {}
                changeset = changeset_payload if isinstance(changeset_payload, ChangeSet) else ChangeSet.from_dict(changeset_payload)
                return {"ok": True, "tool": tool_name, "output": self.apply_changeset_command(changeset)}
            if tool_name == "create_task":
                result = self.create_task_command(
                    require_safe_id(args.get("task_id"), label="task_id"),
                    args.get("task_definition") or {},
                    intent=str(args.get("intent") or ""),
                    rationale=str(args.get("rationale") or ""),
                )
                return {"ok": result.ok, "tool": tool_name, "output": result.to_dict(), "error": result.error}
            if tool_name == "delete_task":
                result = self.delete_task_command(
                    require_safe_id(args.get("task_id"), label="task_id"),
                    intent=str(args.get("intent") or ""),
                    rationale=str(args.get("rationale") or ""),
                )
                return {"ok": result.ok, "tool": tool_name, "output": result.to_dict(), "error": result.error}
            return {"ok": False, "tool": tool_name, "error": f"Tool is declared but not implemented: {tool_name}"}
        except ValueError as exc:
            return {"ok": False, "tool": tool_name, "error": "invalid_arguments", "details": [str(exc)]}
        except Exception as exc:
            return {"ok": False, "tool": tool_name, "error": str(exc)}

    @staticmethod
    def _validate_tool_arguments(schema: dict, arguments: dict) -> list[str]:
        """Small JSON-schema subset validator for Domain Kernel tool inputs."""
        errors: list[str] = []
        if schema.get("type") == "object" and not isinstance(arguments, dict):
            return ["arguments must be an object"]
        required = schema.get("required", []) or []
        for field in required:
            if field not in arguments:
                errors.append(f"missing required field: {field}")
        properties = schema.get("properties", {}) or {}
        if schema.get("additionalProperties") is False:
            for field in arguments:
                if field not in properties:
                    errors.append(f"unexpected field: {field}")
        for field, value in arguments.items():
            field_schema = properties.get(field)
            if not isinstance(field_schema, dict):
                continue
            expected_type = field_schema.get("type")
            if expected_type == "string":
                if not isinstance(value, str):
                    errors.append(f"{field} must be a string")
                elif field_schema.get("minLength") and len(value) < int(field_schema["minLength"]):
                    errors.append(f"{field} must not be empty")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"{field} must be an object")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"{field} must be an array")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"{field} must be a boolean")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"{field} must be a number")
        return errors

    def create_task_command(
        self,
        task_id: str,
        task_definition: dict,
        *,
        intent: str,
        rationale: str = "",
    ):
        """Create a task through the Domain Kernel mutation command."""
        from .domain.commands import create_task

        tasks_payload = load_tasks(self.bot_dir)
        result = create_task(
            tasks_payload,
            task_id,
            task_definition,
            intent=intent,
            rationale=rationale,
        )
        if result.ok and result.updated_tasks is not None:
            save_tasks(result.updated_tasks, self.bot_dir)
            self.reload()
        return result

    def delete_task_command(
        self,
        task_id: str,
        *,
        intent: str,
        rationale: str = "",
    ):
        """Delete a task through the Domain Kernel mutation command."""
        from .domain.commands import delete_task

        tasks_payload = load_tasks(self.bot_dir)
        result = delete_task(
            tasks_payload,
            task_id,
            intent=intent,
            rationale=rationale,
        )
        if result.ok and result.updated_tasks is not None:
            save_tasks(result.updated_tasks, self.bot_dir)
            self.reload()
        return result

    def dry_run_task_command(self, task_id: str):
        """
        Run a task through the Domain Kernel command boundary.

        This keeps the existing scheduler/runner behavior intact while attaching
        TaskSpec, TaskVersion, RunTrace, and DiagnosisReport metadata for UI and
        future Agent tool consumers.
        """
        from .domain.commands import dry_run_task

        tasks_payload = load_tasks(self.bot_dir)
        return dry_run_task(
            tasks_payload,
            task_id,
            run_task_fn=lambda selected_task_id, dry_run=True: self.run_task_by_id(
                selected_task_id,
                dry_run=dry_run,
            ),
        )

    def run_task_command(self, task_id: str):
        """
        Run and send a task through the Domain Kernel command boundary.

        This is the manual execution equivalent of dry_run_task_command().
        """
        from .domain.commands import run_task

        tasks_payload = load_tasks(self.bot_dir)
        return run_task(
            tasks_payload,
            task_id,
            run_task_fn=lambda selected_task_id, dry_run=False: self.run_task_by_id(
                selected_task_id,
                dry_run=dry_run,
            ),
        )

    def propose_task_changeset_command(
        self,
        task_id: str,
        target_task_definition: dict,
        *,
        intent: str,
        rationale: str = "",
    ):
        """Create a ChangeSet for a task config update without mutating storage."""
        from .domain.commands import propose_task_changeset

        tasks_payload = load_tasks(self.bot_dir)
        return propose_task_changeset(
            tasks_payload,
            task_id,
            target_task_definition,
            intent=intent,
            rationale=rationale,
        )

    def apply_changeset_command(self, changeset):
        """Apply a Domain ChangeSet to tasks.json, then reload scheduler state."""
        from .domain.commands import apply_changeset

        tasks_payload = load_tasks(self.bot_dir)
        updated_payload = apply_changeset(tasks_payload, changeset)
        save_tasks(updated_payload, self.bot_dir)
        self.reload()
        return updated_payload

    def run_all_enabled(self, dry_run: bool = False) -> list[dict]:
        """Run all enabled tasks immediately."""
        results = []
        self.reload_if_config_changed()
        for task in self.tasks.values():
            if task.enabled:
                try:
                    result = task.run(dry_run=dry_run, trigger_type="dry_run" if dry_run else "scheduled")
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
