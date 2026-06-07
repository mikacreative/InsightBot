from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from insightbot.config import normalize_task_definition

from .models import ChangeSet, DiagnosisReport, RunTrace, TaskSpec, TaskVersion


class DomainCommandError(ValueError):
    """Raised when a domain command cannot be executed safely."""


@dataclass(frozen=True)
class CommandResult:
    command: str
    ok: bool
    task_spec: TaskSpec | None = None
    task_version: TaskVersion | None = None
    run_result: dict[str, Any] | None = None
    run_trace: RunTrace | None = None
    diagnosis: DiagnosisReport | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "ok": self.ok,
            "task_spec": self.task_spec.to_dict() if self.task_spec else None,
            "task_version": self.task_version.to_dict() if self.task_version else None,
            "run_result": self.run_result,
            "run_trace": self.run_trace.to_dict() if self.run_trace else None,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "error": self.error,
        }


@dataclass(frozen=True)
class TaskMutationResult:
    command: str
    ok: bool
    task_id: str
    changeset: ChangeSet | None = None
    updated_tasks: dict[str, Any] | None = None
    task_spec: TaskSpec | None = None
    task_version: TaskVersion | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "ok": self.ok,
            "task_id": self.task_id,
            "changeset": self.changeset.to_dict() if self.changeset else None,
            "updated_tasks": self.updated_tasks,
            "task_spec": self.task_spec.to_dict() if self.task_spec else None,
            "task_version": self.task_version.to_dict() if self.task_version else None,
            "error": self.error,
        }


def _task_definitions(tasks_payload: dict[str, Any]) -> dict[str, dict]:
    if "tasks" in tasks_payload and isinstance(tasks_payload.get("tasks"), dict):
        return tasks_payload["tasks"]
    return tasks_payload


def get_task_definition(tasks_payload: dict[str, Any], task_id: str) -> dict:
    tasks = _task_definitions(tasks_payload)
    if task_id not in tasks:
        raise DomainCommandError(f"Unknown task_id: {task_id}")
    task_definition = tasks.get(task_id)
    if not isinstance(task_definition, dict):
        raise DomainCommandError(f"Invalid task definition for task_id: {task_id}")
    return task_definition


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _make_changeset_id(task_id: str, operations: list[dict[str, Any]], target_version_id: str) -> str:
    digest = hashlib.sha1(_json_dumps({"task_id": task_id, "operations": operations, "target": target_version_id}).encode("utf-8")).hexdigest()[:12]
    return f"chg_{digest}"


def _diff_dict(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        operations: list[dict[str, Any]] = []
        keys = sorted(set(before.keys()) | set(after.keys()))
        for key in keys:
            child_path = f"{path}/{key}" if path else f"/{key}"
            if key not in before:
                operations.append({"op": "add", "path": child_path, "before": None, "after": deepcopy(after[key])})
            elif key not in after:
                operations.append({"op": "remove", "path": child_path, "before": deepcopy(before[key]), "after": None})
            else:
                operations.extend(_diff_dict(before[key], after[key], child_path))
        return operations
    if before != after:
        return [{"op": "replace", "path": path or "/", "before": deepcopy(before), "after": deepcopy(after)}]
    return []


def _risk_for_operations(operations: list[dict[str, Any]]) -> str:
    paths = [str(op.get("path", "")) for op in operations]
    high_prefixes = ("/channels", "/schedule", "/enabled", "/pipeline")
    medium_prefixes = ("/sources", "/sections", "/pipeline_config")
    if any(path.startswith(high_prefixes) for path in paths):
        return "medium"
    if any(path.startswith(medium_prefixes) for path in paths):
        return "medium"
    return "low"


def _force_changeset_risk(changeset: ChangeSet, risk_level: str) -> ChangeSet:
    return ChangeSet(
        changeset_id=changeset.changeset_id,
        task_id=changeset.task_id,
        intent=changeset.intent,
        operations=changeset.operations,
        risk_level=risk_level,
        rationale=changeset.rationale,
        base_version_id=changeset.base_version_id,
        target_version_id=changeset.target_version_id,
        created_at=changeset.created_at,
    )


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        raise DomainCommandError("Cannot replace root task definition via changeset operation.")
    current: Any = root
    for part in parts[:-1]:
        if not isinstance(current, dict):
            raise DomainCommandError(f"Cannot traverse non-object path: {path}")
        current = current.setdefault(part, {})
    if not isinstance(current, dict):
        raise DomainCommandError(f"Cannot set non-object path: {path}")
    current[parts[-1]] = deepcopy(value)


def _remove_path(root: dict[str, Any], path: str) -> None:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        raise DomainCommandError("Cannot remove root task definition via changeset operation.")
    current: Any = root
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def get_task_spec(tasks_payload: dict[str, Any], task_id: str) -> TaskSpec:
    return TaskSpec.from_task_definition(task_id, get_task_definition(tasks_payload, task_id))


def get_task_version(tasks_payload: dict[str, Any], task_id: str) -> TaskVersion:
    return TaskVersion.from_spec(get_task_spec(tasks_payload, task_id))


def validate_task(
    tasks_payload: dict[str, Any],
    task_id: str,
    *,
    channels_payload: dict[str, Any] | None = None,
) -> tuple[TaskSpec, DiagnosisReport]:
    spec = get_task_spec(tasks_payload, task_id)
    known_channels = None
    if channels_payload is not None:
        known_channels = set((channels_payload.get("channels", {}) or {}).keys())
    return spec, DiagnosisReport.from_task_spec(spec, known_channels=known_channels)


def diagnose_run(run_trace: RunTrace) -> DiagnosisReport:
    return DiagnosisReport.from_run_trace(run_trace)


def _execute_task_command(
    tasks_payload: dict[str, Any],
    task_id: str,
    *,
    run_task_fn: Callable[[str], dict] | Callable[..., dict],
    command: str,
    dry_run: bool,
    trigger_type: str,
) -> CommandResult:
    spec = get_task_spec(tasks_payload, task_id)
    task_version = TaskVersion.from_spec(spec)
    try:
        run_result = run_task_fn(task_id, dry_run=dry_run)
        run_trace = RunTrace.from_task_result(
            run_result,
            task_version_id=task_version.version_id,
            trigger_type=trigger_type,
        )
        diagnosis = DiagnosisReport.from_run_trace(run_trace)
        return CommandResult(
            command=command,
            ok=bool(run_result.get("ok", False)),
            task_spec=spec,
            task_version=task_version,
            run_result=run_result,
            run_trace=run_trace,
            diagnosis=diagnosis,
            error=run_result.get("error"),
        )
    except Exception as exc:
        return CommandResult(
            command=command,
            ok=False,
            task_spec=spec,
            task_version=task_version,
            diagnosis=DiagnosisReport.from_task_spec(spec),
            error=str(exc),
        )


def dry_run_task(
    tasks_payload: dict[str, Any],
    task_id: str,
    *,
    run_task_fn: Callable[[str], dict] | Callable[..., dict],
) -> CommandResult:
    return _execute_task_command(
        tasks_payload,
        task_id,
        run_task_fn=run_task_fn,
        command="dry_run_task",
        dry_run=True,
        trigger_type="dry_run",
    )


def run_task(
    tasks_payload: dict[str, Any],
    task_id: str,
    *,
    run_task_fn: Callable[[str], dict] | Callable[..., dict],
) -> CommandResult:
    return _execute_task_command(
        tasks_payload,
        task_id,
        run_task_fn=run_task_fn,
        command="run_task",
        dry_run=False,
        trigger_type="manual",
    )


def propose_task_changeset(
    tasks_payload: dict[str, Any],
    task_id: str,
    target_task_definition: dict[str, Any],
    *,
    intent: str,
    rationale: str = "",
) -> ChangeSet:
    current_definition = normalize_task_definition(get_task_definition(tasks_payload, task_id))
    target_definition = normalize_task_definition(target_task_definition)
    current_spec = TaskSpec.from_task_definition(task_id, current_definition)
    target_spec = TaskSpec.from_task_definition(task_id, target_definition)
    base_version = TaskVersion.from_spec(current_spec)
    target_version = TaskVersion.from_spec(target_spec)
    operations = _diff_dict(current_definition, target_definition)
    return ChangeSet(
        changeset_id=_make_changeset_id(task_id, operations, target_version.version_id),
        task_id=task_id,
        intent=intent,
        operations=operations,
        risk_level=_risk_for_operations(operations),
        rationale=rationale,
        base_version_id=base_version.version_id,
        target_version_id=target_version.version_id,
    )


def apply_changeset(tasks_payload: dict[str, Any], changeset: ChangeSet) -> dict[str, Any]:
    updated_payload = deepcopy(tasks_payload)
    updated_payload.setdefault("tasks", {})
    task_definition = normalize_task_definition(get_task_definition(updated_payload, changeset.task_id))
    for operation in changeset.operations:
        op = operation.get("op")
        path = str(operation.get("path", ""))
        if op in {"add", "replace"}:
            _set_path(task_definition, path, operation.get("after"))
        elif op == "remove":
            _remove_path(task_definition, path)
        else:
            raise DomainCommandError(f"Unsupported changeset operation: {op}")
    updated_payload["tasks"][changeset.task_id] = normalize_task_definition(task_definition)
    return updated_payload


def create_task(
    tasks_payload: dict[str, Any],
    task_id: str,
    task_definition: dict[str, Any],
    *,
    intent: str,
    rationale: str = "",
) -> TaskMutationResult:
    try:
        if task_id in _task_definitions(tasks_payload):
            raise DomainCommandError(f"Task already exists: {task_id}")
        normalized_task = normalize_task_definition(task_definition)
        base_payload = deepcopy(tasks_payload)
        base_payload.setdefault("tasks", {})
        base_payload["tasks"][task_id] = {}
        changeset = propose_task_changeset(
            base_payload,
            task_id,
            normalized_task,
            intent=intent,
            rationale=rationale,
        )
        changeset = _force_changeset_risk(changeset, "medium")
        updated_tasks = apply_changeset(base_payload, changeset)
        spec = get_task_spec(updated_tasks, task_id)
        return TaskMutationResult(
            command="create_task",
            ok=True,
            task_id=task_id,
            changeset=changeset,
            updated_tasks=updated_tasks,
            task_spec=spec,
            task_version=TaskVersion.from_spec(spec),
        )
    except Exception as exc:
        return TaskMutationResult(command="create_task", ok=False, task_id=task_id, error=str(exc))


def delete_task(
    tasks_payload: dict[str, Any],
    task_id: str,
    *,
    intent: str,
    rationale: str = "",
) -> TaskMutationResult:
    try:
        current_definition = get_task_definition(tasks_payload, task_id)
        current_spec = get_task_spec(tasks_payload, task_id)
        base_version = TaskVersion.from_spec(current_spec)
        operations = [
            {
                "op": "remove",
                "path": f"/tasks/{task_id}",
                "before": deepcopy(current_definition),
                "after": None,
            }
        ]
        digest = hashlib.sha1(_json_dumps({"task_id": task_id, "operations": operations}).encode("utf-8")).hexdigest()[:12]
        changeset = ChangeSet(
            changeset_id=f"chg_{digest}",
            task_id=task_id,
            intent=intent,
            operations=operations,
            risk_level="high",
            rationale=rationale,
            base_version_id=base_version.version_id,
            target_version_id=None,
        )
        updated_tasks = deepcopy(tasks_payload)
        updated_tasks.setdefault("tasks", {})
        updated_tasks["tasks"].pop(task_id, None)
        return TaskMutationResult(
            command="delete_task",
            ok=True,
            task_id=task_id,
            changeset=changeset,
            updated_tasks=updated_tasks,
        )
    except Exception as exc:
        return TaskMutationResult(command="delete_task", ok=False, task_id=task_id, error=str(exc))
