from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from insightbot.config import normalize_task_definition


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalize_rss_sources(sources: dict) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate((sources or {}).get("rss", []) or []):
        if not isinstance(item, dict):
            raw_url = str(item or "").strip()
            if not raw_url:
                continue
            item = {"url": raw_url}

        raw_url = str(item.get("url", "")).strip()
        if not raw_url:
            continue
        source_id = str(item.get("id") or item.get("source_id") or f"rss_{index + 1}").strip()
        normalized.append(
            {
                "source_id": source_id,
                "name": str(item.get("name") or source_id or raw_url).strip(),
                "url": raw_url,
                "enabled": bool(item.get("enabled", True)),
                "section_hints": [
                    str(v).strip()
                    for v in _as_list(item.get("section_hints"))
                    if str(v).strip()
                ],
                "tags": [
                    str(v).strip()
                    for v in _as_list(item.get("tags"))
                    if str(v).strip()
                ],
            }
        )
    return sorted(normalized, key=lambda item: (item["source_id"], item["url"]))


def _normalize_search_sources(sources: dict) -> dict:
    search = dict((sources or {}).get("search", {}) or {})
    queries = []
    for query in search.get("queries", []) or []:
        if isinstance(query, str):
            keywords = query.strip()
            section_hints: list[str] = []
            max_results = 10
        elif isinstance(query, dict):
            keywords = str(query.get("keywords", "")).strip()
            section_hints = [
                str(v).strip()
                for v in _as_list(query.get("section_hints"))
                if str(v).strip()
            ]
            max_results = int(query.get("max_results", 10) or 10)
        else:
            continue
        if not keywords:
            continue
        queries.append(
            {
                "keywords": keywords,
                "section_hints": section_hints,
                "max_results": max_results,
            }
        )
    return {
        "enabled": bool(search.get("enabled", False)),
        "provider": str(search.get("provider", "")).strip() or None,
        "queries": sorted(queries, key=lambda item: (item["keywords"], item["max_results"])),
    }


def _normalize_sections(sections: dict) -> dict:
    normalized = {}
    for name, payload in (sections or {}).items():
        section_name = str(name).strip()
        if not section_name:
            continue
        section = payload or {}
        normalized[section_name] = {
            "prompt": str(section.get("prompt", "")).strip(),
            "keywords": [
                str(v).strip()
                for v in _as_list(section.get("keywords"))
                if str(v).strip()
            ],
            "source_hints": [
                str(v).strip()
                for v in _as_list(section.get("source_hints"))
                if str(v).strip()
            ],
        }
    return normalized


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    name: str
    enabled: bool
    pipeline: str
    sections: dict[str, dict]
    sources: dict[str, Any]
    channels: list[str]
    schedule: dict[str, Any]
    quality_policy: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_task_definition(cls, task_id: str, task_definition: dict | None) -> "TaskSpec":
        normalized = normalize_task_definition(task_definition or {})
        sources = normalized.get("sources", {}) or {}
        return cls(
            task_id=task_id,
            name=str(normalized.get("name") or task_id).strip(),
            enabled=bool(normalized.get("enabled", False)),
            pipeline=str(normalized.get("pipeline") or normalized.get("_task_pipeline") or "editorial").strip(),
            sections=_normalize_sections(normalized.get("sections", {}) or {}),
            sources={
                "rss": _normalize_rss_sources(sources),
                "search": _normalize_search_sources(sources),
            },
            channels=[
                str(channel).strip()
                for channel in _as_list(normalized.get("channels"))
                if str(channel).strip()
            ],
            schedule=dict(normalized.get("schedule", {}) or {}),
            quality_policy=dict(normalized.get("pipeline_config", {}) or {}),
            raw=normalized,
        )

    @property
    def section_names(self) -> list[str]:
        return list(self.sections.keys())

    @property
    def enabled_source_count(self) -> int:
        return sum(1 for item in self.sources.get("rss", []) if item.get("enabled"))

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "enabled": self.enabled,
            "pipeline": self.pipeline,
            "sections": self.sections,
            "sources": self.sources,
            "channels": self.channels,
            "schedule": self.schedule,
            "quality_policy": self.quality_policy,
        }

    def canonical_dict(self) -> dict:
        data = self.to_dict()
        data["channels"] = sorted(data["channels"])
        data["sources"] = {
            "rss": sorted(data["sources"].get("rss", []), key=lambda item: (item["source_id"], item["url"])),
            "search": data["sources"].get("search", {}),
        }
        return data


@dataclass(frozen=True)
class TaskVersion:
    task_id: str
    version_id: str
    fingerprint: str
    created_at: str
    spec: TaskSpec

    @classmethod
    def from_spec(cls, spec: TaskSpec, *, created_at: str | None = None) -> "TaskVersion":
        fingerprint = hashlib.sha256(_json_dumps(spec.canonical_dict()).encode("utf-8")).hexdigest()[:16]
        return cls(
            task_id=spec.task_id,
            version_id=f"taskv_{fingerprint}",
            fingerprint=fingerprint,
            created_at=created_at or _now_iso(),
            spec=spec,
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "version_id": self.version_id,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "spec": self.spec.to_dict(),
        }


@dataclass(frozen=True)
class RunStage:
    stage: str
    ok: bool = True
    input_count: int = 0
    output_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RunTrace:
    run_id: str
    task_id: str
    task_version_id: str | None
    trigger_type: str
    ok: bool
    pipeline: str
    stages: list[RunStage]
    channel_results: list[dict]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    final_markdown: str = ""

    @classmethod
    def from_task_result(
        cls,
        result: dict,
        *,
        task_version_id: str | None,
        trigger_type: str,
        run_id: str | None = None,
    ) -> "RunTrace":
        stage_results = result.get("stage_results", {}) or {}
        global_candidates = stage_results.get("global_candidates", [])
        screened_items = (stage_results.get("screened_result", {}) or {}).get("screened", [])
        assignment = stage_results.get("assignment_result", {}) or {}
        category_map = assignment.get("category_candidate_map", {}) or {}
        unassigned = assignment.get("unassigned", []) or []
        category_results = stage_results.get("category_results", {}) or {}
        selected_count = sum(
            len((payload or {}).get("selected_items", []) or [])
            for payload in category_results.values()
            if isinstance(payload, dict)
        )

        if not isinstance(global_candidates, list):
            global_candidates = []
        if not isinstance(screened_items, list):
            screened_items = []

        stages = [
            RunStage(stage="fetch", output_count=len(global_candidates)),
            RunStage(stage="screen", input_count=len(global_candidates), output_count=len(screened_items)),
            RunStage(
                stage="assign",
                input_count=len(screened_items),
                output_count=sum(len(items or []) for items in category_map.values()),
                warnings=[f"{len(unassigned)} unassigned candidates"] if unassigned else [],
                metadata={"unassigned_count": len(unassigned)},
            ),
            RunStage(stage="generate", input_count=sum(len(items or []) for items in category_map.values()), output_count=selected_count),
            RunStage(stage="render", output_count=1 if str(result.get("final_markdown", "")).strip() else 0),
            RunStage(
                stage="send",
                ok=all(bool(item.get("ok")) for item in result.get("channel_results", []) or []),
                output_count=sum(1 for item in result.get("channel_results", []) or [] if item.get("ok")),
                errors=[
                    str(item.get("error"))
                    for item in result.get("channel_results", []) or []
                    if item.get("error")
                ],
            ),
        ]
        errors = [str(result["error"])] if result.get("error") else []
        return cls(
            run_id=run_id or f"run_{hashlib.sha1(_json_dumps(result).encode('utf-8')).hexdigest()[:12]}",
            task_id=str(result.get("task_id") or result.get("_selected_task_id") or ""),
            task_version_id=task_version_id,
            trigger_type=trigger_type,
            ok=bool(result.get("ok", False)),
            pipeline=str(result.get("pipeline") or ""),
            stages=stages,
            channel_results=list(result.get("channel_results", []) or []),
            errors=errors,
            final_markdown=str(result.get("final_markdown", "") or ""),
        )

    def stage(self, name: str) -> RunStage:
        for item in self.stages:
            if item.stage == name:
                return item
        raise KeyError(name)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_version_id": self.task_version_id,
            "trigger_type": self.trigger_type,
            "ok": self.ok,
            "pipeline": self.pipeline,
            "stages": [stage.to_dict() for stage in self.stages],
            "channel_results": self.channel_results,
            "errors": self.errors,
            "warnings": self.warnings,
            "final_markdown": self.final_markdown,
        }


@dataclass(frozen=True)
class DiagnosisFinding:
    type: str
    severity: str
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
            "suggested_actions": self.suggested_actions,
        }


@dataclass(frozen=True)
class DiagnosisReport:
    diagnosis_id: str
    target_id: str
    summary: str
    severity: str
    findings: list[DiagnosisFinding]

    @classmethod
    def from_task_spec(cls, spec: TaskSpec, *, known_channels: set[str] | None = None) -> "DiagnosisReport":
        findings: list[DiagnosisFinding] = []
        if not spec.sections:
            findings.append(
                DiagnosisFinding(
                    type="missing_sections",
                    severity="error",
                    message="任务没有配置任何板块。",
                    suggested_actions=["update_task_spec"],
                )
            )
        else:
            for section_name, section in spec.sections.items():
                if not str((section or {}).get("prompt", "")).strip():
                    findings.append(
                        DiagnosisFinding(
                            type="missing_section_prompt",
                            severity="warning",
                            message=f"栏目「{section_name}」还没有填写筛选 Prompt。",
                            evidence=[{"field_path": f"sections.{section_name}.prompt"}],
                            suggested_actions=["update_task_spec"],
                        )
                    )
        if spec.enabled_source_count == 0 and not spec.sources.get("search", {}).get("enabled"):
            findings.append(
                DiagnosisFinding(
                    type="missing_sources",
                    severity="error",
                    message="任务没有可用信源。",
                    suggested_actions=["add_source", "bind_source_to_section"],
                )
            )
        if not spec.channels:
            findings.append(
                DiagnosisFinding(
                    type="missing_channels",
                    severity="error",
                    message="任务没有配置推送频道。",
                    evidence=[{"field_path": "channels"}],
                    suggested_actions=["bind_channel"],
                )
            )
        elif known_channels is not None:
            for channel_id in spec.channels:
                if channel_id not in known_channels:
                    findings.append(
                        DiagnosisFinding(
                            type="channel_not_found",
                            severity="error",
                            message=f"任务引用的频道「{channel_id}」不存在。",
                            evidence=[{"field_path": "channels", "channel_id": channel_id}],
                            suggested_actions=["bind_channel", "create_channel"],
                        )
                    )
        if "hour" not in spec.schedule or "minute" not in spec.schedule:
            findings.append(
                DiagnosisFinding(
                    type="missing_schedule",
                    severity="error",
                    message="任务缺少完整的调度时间。",
                    evidence=[{"field_path": "schedule"}],
                    suggested_actions=["update_task_spec"],
                )
            )
        return cls._build(target_id=spec.task_id, findings=findings)

    @classmethod
    def from_run_trace(cls, trace: RunTrace) -> "DiagnosisReport":
        findings: list[DiagnosisFinding] = []
        if trace.stage("fetch").output_count == 0:
            findings.append(
                DiagnosisFinding(
                    type="empty_candidates",
                    severity="warning",
                    message="运行没有抓到候选内容。",
                    suggested_actions=["check_source_health", "add_source"],
                )
            )
        elif trace.stage("screen").output_count == 0:
            findings.append(
                DiagnosisFinding(
                    type="empty_screening",
                    severity="warning",
                    message="AI 初筛没有保留候选内容。",
                    suggested_actions=["review_screening_policy", "dry_run_task"],
                )
            )
        if trace.stage("assign").warning_count:
            findings.append(
                DiagnosisFinding(
                    type="unassigned_candidates",
                    severity="info",
                    message="部分候选没有分配到板块。",
                    evidence=[{"unassigned_count": trace.stage("assign").metadata.get("unassigned_count", 0)}],
                    suggested_actions=["review_section_hints"],
                )
            )
        if trace.stage("render").output_count == 0:
            findings.append(
                DiagnosisFinding(
                    type="empty_final_output",
                    severity="warning",
                    message="运行没有生成最终简报内容。",
                    suggested_actions=["review_generation_stage", "dry_run_task"],
                )
            )
        failed_channels = [item for item in trace.channel_results if not item.get("ok")]
        if failed_channels:
            findings.append(
                DiagnosisFinding(
                    type="channel_failure",
                    severity="error",
                    message="至少一个频道发送失败。",
                    evidence=failed_channels,
                    suggested_actions=["test_channel", "retry_failed_stage"],
                )
            )
        return cls._build(target_id=trace.run_id, findings=findings)

    @classmethod
    def _build(cls, *, target_id: str, findings: list[DiagnosisFinding]) -> "DiagnosisReport":
        severity_order = {"error": 3, "warning": 2, "info": 1}
        severity = "ok"
        if findings:
            severity = max(findings, key=lambda item: severity_order.get(item.severity, 0)).severity
        summary = "未发现明显问题。" if not findings else f"发现 {len(findings)} 个诊断项。"
        digest = hashlib.sha1(_json_dumps([finding.to_dict() for finding in findings]).encode("utf-8")).hexdigest()[:12]
        return cls(
            diagnosis_id=f"diag_{digest}",
            target_id=target_id,
            summary=summary,
            severity=severity,
            findings=findings,
        )

    def to_dict(self) -> dict:
        return {
            "diagnosis_id": self.diagnosis_id,
            "target_id": self.target_id,
            "summary": self.summary,
            "severity": self.severity,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class ChangeSet:
    changeset_id: str
    task_id: str
    intent: str
    operations: list[dict[str, Any]]
    risk_level: str = "low"
    rationale: str = ""
    base_version_id: str | None = None
    target_version_id: str | None = None
    created_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChangeSet":
        return cls(
            changeset_id=str(payload.get("changeset_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            intent=str(payload.get("intent") or ""),
            operations=list(payload.get("operations", []) or []),
            risk_level=str(payload.get("risk_level") or "low"),
            rationale=str(payload.get("rationale") or ""),
            base_version_id=payload.get("base_version_id"),
            target_version_id=payload.get("target_version_id"),
            created_at=str(payload.get("created_at") or _now_iso()),
        )

    def to_dict(self) -> dict:
        return {
            "changeset_id": self.changeset_id,
            "task_id": self.task_id,
            "intent": self.intent,
            "operations": self.operations,
            "risk_level": self.risk_level,
            "rationale": self.rationale,
            "base_version_id": self.base_version_id,
            "target_version_id": self.target_version_id,
            "created_at": self.created_at,
        }
