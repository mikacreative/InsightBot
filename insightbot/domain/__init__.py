"""Domain Kernel primitives for task specs, versions, traces, and diagnosis."""

from .commands import (
    CommandResult,
    DomainCommandError,
    TaskMutationResult,
    apply_changeset,
    create_task,
    delete_task,
    diagnose_run,
    dry_run_task,
    get_task_spec,
    get_task_version,
    propose_task_changeset,
    run_task,
    validate_task,
)
from .compat import validation_result_from_domain
from .models import (
    ChangeSet,
    DiagnosisFinding,
    DiagnosisReport,
    RunStage,
    RunTrace,
    TaskSpec,
    TaskVersion,
)
from .tools import get_tool_manifest

__all__ = [
    "ChangeSet",
    "CommandResult",
    "DiagnosisFinding",
    "DiagnosisReport",
    "DomainCommandError",
    "RunStage",
    "RunTrace",
    "TaskSpec",
    "TaskVersion",
    "TaskMutationResult",
    "apply_changeset",
    "create_task",
    "delete_task",
    "diagnose_run",
    "dry_run_task",
    "get_task_spec",
    "get_task_version",
    "get_tool_manifest",
    "propose_task_changeset",
    "run_task",
    "validate_task",
    "validation_result_from_domain",
]
