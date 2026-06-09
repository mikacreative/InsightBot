"""Machine-readable manifest for Domain Kernel commands.

The manifest is intentionally static for now. It describes the command boundary
that both the Streamlit UI and future Agent tools should respect.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_STRING_SCHEMA = {"type": "string", "minLength": 1}
_OBJECT_SCHEMA = {"type": "object"}


def _tool(
    *,
    name: str,
    description: str,
    category: str,
    risk_level: str,
    requires_approval: bool,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "category": category,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "input_schema": input_schema,
        "output_schema": output_schema or _OBJECT_SCHEMA,
    }


def get_tool_manifest() -> dict[str, Any]:
    """Return a JSON-safe manifest for current Domain Kernel commands."""
    manifest = {
        "manifest_id": "insightbot_domain_tools_v1",
        "name": "InsightBot Domain Tools",
        "domain": "InsightBot Domain Kernel",
        "version": 1,
        "tools": [
            _tool(
                name="list_tasks",
                description="List available task IDs and basic task metadata.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="list_task_cards",
                description="List product-facing task cards for the Insight Workbench.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_workspace_state",
                description="Read the shared Insight Workbench state for all tasks or one selected task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {"selected_task_id": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_task_status",
                description="Read the product-facing status card for one task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_latest_run_evidence",
                description="Read compact RunEvidence for the latest persisted run of one task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_source_health_summary",
                description="Read compact source health summary for one task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_task_spec",
                description="Read the canonical TaskSpec for one task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="get_task_version",
                description="Read the deterministic TaskVersion for one task.",
                category="read",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="validate_task",
                description="Validate task readiness and return a structured DiagnosisReport.",
                category="diagnosis",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="dry_run_task",
                description="Run one task without sending channel messages and return RunTrace evidence.",
                category="execution",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="run_task",
                description="Run one task and send output through configured channels.",
                category="execution",
                risk_level="high",
                requires_approval=True,
                input_schema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {"task_id": _STRING_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="diagnose_run",
                description="Diagnose an existing RunTrace.",
                category="diagnosis",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["run_trace"],
                    "properties": {"run_trace": _OBJECT_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="propose_task_changeset",
                description="Compare a target task definition with the current task and return a ChangeSet.",
                category="mutation_plan",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id", "target_task_definition", "intent"],
                    "properties": {
                        "task_id": _STRING_SCHEMA,
                        "target_task_definition": _OBJECT_SCHEMA,
                        "intent": _STRING_SCHEMA,
                        "rationale": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="propose_task_update",
                description="Product-facing alias for proposing a task ChangeSet without mutating storage.",
                category="mutation_plan",
                risk_level="low",
                requires_approval=False,
                input_schema={
                    "type": "object",
                    "required": ["task_id", "target_task_definition", "intent"],
                    "properties": {
                        "task_id": _STRING_SCHEMA,
                        "target_task_definition": _OBJECT_SCHEMA,
                        "intent": _STRING_SCHEMA,
                        "rationale": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="apply_changeset",
                description="Apply a previously proposed ChangeSet to task storage.",
                category="mutation",
                risk_level="medium",
                requires_approval=True,
                input_schema={
                    "type": "object",
                    "required": ["changeset"],
                    "properties": {"changeset": _OBJECT_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="approve_and_apply_changeset",
                description="Product-facing alias for applying an approved ChangeSet to task storage.",
                category="mutation",
                risk_level="medium",
                requires_approval=True,
                input_schema={
                    "type": "object",
                    "required": ["changeset"],
                    "properties": {"changeset": _OBJECT_SCHEMA},
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="create_task",
                description="Create a new task from a full task definition.",
                category="mutation",
                risk_level="medium",
                requires_approval=True,
                input_schema={
                    "type": "object",
                    "required": ["task_id", "task_definition", "intent"],
                    "properties": {
                        "task_id": _STRING_SCHEMA,
                        "task_definition": _OBJECT_SCHEMA,
                        "intent": _STRING_SCHEMA,
                        "rationale": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            _tool(
                name="delete_task",
                description="Delete an existing task from task storage.",
                category="mutation",
                risk_level="high",
                requires_approval=True,
                input_schema={
                    "type": "object",
                    "required": ["task_id", "intent"],
                    "properties": {
                        "task_id": _STRING_SCHEMA,
                        "intent": _STRING_SCHEMA,
                        "rationale": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
        ],
        "resources": [
            {"uri_template": "task://{task_id}/spec", "description": "Canonical TaskSpec for a task."},
            {"uri_template": "task://{task_id}/version", "description": "Stable TaskVersion fingerprint."},
            {"uri_template": "task://{task_id}/runs/latest", "description": "Latest RunTrace when persisted."},
            {"uri_template": "diagnosis://{diagnosis_id}", "description": "Structured DiagnosisReport."},
        ],
    }
    return deepcopy(manifest)
