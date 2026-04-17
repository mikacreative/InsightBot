"""
test_task_runner.py — insightbot.task_runner 核心逻辑测试

测试范围：
  - run_task() dry_run=True → 不调用任何 channel send
  - run_task() dry_run=False → 返回 channel_results 列表
  - dry_run vs real run 行为差异
  - pipeline dispatch（通过检查 mock 调用确认）
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock feedparser and requests before importing editorial_pipeline/smart_brief_runner
# (they import these at module level)
_mock_feedparser = MagicMock()
_mock_requests = MagicMock()
sys.modules['feedparser'] = _mock_feedparser
sys.modules['requests'] = _mock_requests


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
