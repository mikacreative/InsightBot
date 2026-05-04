"""
test_task_runner.py — insightbot.task_runner 核心逻辑测试

测试范围：
  - run_task() dry_run=True → 不调用任何 channel send
  - run_task() dry_run=False → 返回 channel_results 列表
  - dry_run vs real run 行为差异
  - pipeline dispatch（通过检查 mock 调用确认）
"""

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Mock feedparser and requests before importing editorial_pipeline/smart_brief_runner
# (they import these at module level)
_mock_feedparser = MagicMock()
_mock_requests = MagicMock()
sys.modules['feedparser'] = _mock_feedparser
sys.modules['requests'] = _mock_requests


def test_normalize_search_queries_accepts_task_config_dicts():
    from insightbot.task_runner import _normalize_search_queries

    queries = [
        {"keywords": "AI marketing trend case", "category_hint": "AI and Martech"},
        " brand campaign marketing case ",
        {"keywords": "   "},
        "",
    ]

    assert _normalize_search_queries(queries) == [
        "AI marketing trend case",
        "brand campaign marketing case",
    ]


def test_editorial_intelligence_pipeline_exposes_structured_shortlist():
    from insightbot.task_runner import run_task

    @dataclass(slots=True)
    class BriefingResult:
        ok: bool
        source_summary: dict[str, Any] = field(default_factory=dict)
        candidate_pool: list[dict[str, Any]] = field(default_factory=list)
        shortlist: list[dict[str, Any]] = field(default_factory=list)
        section_assignments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
        final_brief: dict[str, Any] = field(default_factory=dict)
        diagnostics: dict[str, Any] = field(default_factory=dict)

    @dataclass(slots=True)
    class BriefingGoal:
        topic: str
        queries: list[str]
        description: str = ""
        audience: str = ""

    @dataclass(slots=True)
    class SourceStrategy:
        primary_sources: list[str]
        search_enabled: bool = False

    @dataclass(slots=True)
    class SourceWeightConfig:
        search_providers: dict[str, Any] = field(default_factory=dict)

    @dataclass(slots=True)
    class SearchProvider:
        provider_id: str
        name: str
        weight: float
        enabled: bool = True
        api_key: str = ""
        base_url: str = ""
        timeout_s: int = 0

    contracts_module = ModuleType("editorial_intelligence.contracts")
    contracts_module.BriefingGoal = BriefingGoal
    contracts_module.SourceStrategy = SourceStrategy
    contracts_module.SourceWeightConfig = SourceWeightConfig

    source_weight_module = ModuleType("editorial_intelligence.contracts.source_weight")
    source_weight_module.SearchProvider = SearchProvider

    workflow_module = ModuleType("editorial_intelligence.workflows.editorial_pipeline")
    workflows_module = ModuleType("editorial_intelligence.workflows")
    package_module = ModuleType("editorial_intelligence")

    fake_config = {
        "_task_pipeline": "editorial",
        "_editorial_pipeline_mode": "editorial-intelligence",
        "_task_channels": [],
        "feeds": {},
        "search": {"enabled": False, "queries": []},
        "pipeline_config": {"shortlist_size": 1},
    }
    fake_ei_result = BriefingResult(
        ok=True,
        candidate_pool=[{"title": "A"}, {"title": "B"}],
        shortlist=[
            {
                "title": "Brand launches AI shopping assistant",
                "why_it_matters": "It affects retail conversion.",
            }
        ],
        section_assignments={"Client Conversation Starters": [{"title": "Brand launches AI shopping assistant"}]},
        final_brief={"markdown": "## Brief"},
        diagnostics={"source_counts": {"shortlisted": 1}},
    )
    workflow_module.run_editorial_pipeline = MagicMock(return_value=fake_ei_result)
    workflows_module.editorial_pipeline = workflow_module

    with patch.dict(
        sys.modules,
        {
            "editorial_intelligence": package_module,
            "editorial_intelligence.contracts": contracts_module,
            "editorial_intelligence.contracts.source_weight": source_weight_module,
            "editorial_intelligence.workflows": workflows_module,
            "editorial_intelligence.workflows.editorial_pipeline": workflow_module,
        },
    ):
        with patch("insightbot.task_runner.append_run_record"):
            result = run_task("room_client_radar", lambda: fake_config, dry_run=True)

    assert result["stage_results"]["shortlist"] == fake_ei_result.shortlist
    assert result["stage_results"]["candidate_pool"] == fake_ei_result.candidate_pool
    assert result["stage_results"]["section_assignments"] == fake_ei_result.section_assignments


class TestRunTaskDryRun:
    """dry_run=True 时不发送任何 channel，完整返回 stage_results。"""

    def test_dry_run_returns_final_markdown_no_channel_results(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": ["wecom_main"],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {
                "ok": True,
                "final_markdown": "## 报告内容",
                "screened_result": {},
                "error": None,
            }
            with patch("insightbot.task_runner.send_to_channel") as mock_send, \
                 patch("insightbot.task_runner.append_run_record") as mock_history:
                result = run_task("daily_brief", fake_loader, dry_run=True)

                assert result["dry_run"] is True
                assert result["channel_results"] == []
                assert result["final_markdown"] == "## 报告内容"
                assert "stage_results" in result
                mock_send.assert_not_called()
                mock_history.assert_called_once()

    def test_dry_run_with_classic_pipeline(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "classic",
            "_task_channels": ["wecom_main"],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_classic_pipeline") as mock_classic:
            mock_classic.return_value = {
                "ok": True,
                "final_markdown": "## 经典报告",
                "error": None,
            }
            with patch("insightbot.task_runner.send_to_channel") as mock_send, \
                 patch("insightbot.task_runner.append_run_record") as mock_history:
                result = run_task("weekly_report", fake_loader, dry_run=True)

                assert result["dry_run"] is True
                assert result["pipeline"] == "classic"
                mock_send.assert_not_called()
                mock_history.assert_called_once()


class TestRunTaskReal:
    """dry_run=False 时发送内容到所有配置的 channel。"""

    def test_real_run_calls_send_to_channel_per_channel(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": ["ch1", "ch2"],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
            "settings": {},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {
                "ok": True,
                "final_markdown": "## 报告",
                "error": None,
            }
            with patch("insightbot.task_runner.send_to_channel") as mock_send, \
                 patch("insightbot.task_runner.append_run_record") as mock_history:
                mock_send.return_value = True
                result = run_task("daily_brief", fake_loader, dry_run=False)

                assert result["dry_run"] is False
                assert len(result["channel_results"]) == 2
                assert result["channel_results"][0]["channel_id"] == "ch1"
                assert result["channel_results"][1]["channel_id"] == "ch2"
                mock_history.assert_called_once()

    def test_pipeline_dispatch_editorial(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": [],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {
                "ok": True,
                "final_markdown": " editorial ",
                "error": None,
            }
            result = run_task("t1", fake_loader, dry_run=True)
            mock_ep.assert_called_once()
            assert result["pipeline"] == "editorial"

    def test_pipeline_dispatch_classic(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "classic",
            "_task_channels": [],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_classic_pipeline") as mock_classic:
            mock_classic.return_value = {
                "ok": True,
                "final_markdown": " classic ",
                "error": None,
            }
            result = run_task("t1", fake_loader, dry_run=True)
            mock_classic.assert_called_once()
            assert result["pipeline"] == "classic"

    def test_pipeline_exception_returns_error(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": [],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.side_effect = Exception("AI API failed")
            with patch("insightbot.task_runner.append_run_record") as mock_history:
                result = run_task("t1", fake_loader, dry_run=True)

            assert result["ok"] is False
            assert "AI API failed" in result["error"]
            mock_history.assert_called_once()

    def test_send_to_channel_called_with_content(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": ["wecom_main"],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
            "settings": {"report_title": "早报"},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {
                "ok": True,
                "final_markdown": "## 报告",
                "error": None,
            }
            with patch("insightbot.task_runner.send_to_channel") as mock_send:
                mock_send.return_value = True
                result = run_task("daily_brief", fake_loader, dry_run=False)

                assert result["channel_results"][0]["ok"] is True

    def test_channel_result_false_when_header_send_fails(self):
        from insightbot.task_runner import run_task

        fake_config = {
            "_task_pipeline": "editorial",
            "_task_channels": ["wecom_main"],
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
            "settings": {"report_title": "早报"},
        }
        fake_loader = lambda: fake_config

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {
                "ok": True,
                "final_markdown": "## 报告",
                "error": None,
            }
            with patch("insightbot.task_runner.send_to_channel", side_effect=[False]):
                result = run_task("daily_brief", fake_loader, dry_run=False)

        assert result["channel_results"][0]["ok"] is False
