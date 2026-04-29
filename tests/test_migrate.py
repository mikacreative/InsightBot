"""
test_migrate.py — insightbot.migrate 核心逻辑测试

测试范围：
  - migrate_from_v1() 生成正确的 channels.json
  - migrate_from_v1() 生成正确的 tasks.json
  - 重复调用是安全的（文件已存在时跳过）
"""

import json
import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch


class TestMigrateFromV1:
    def test_creates_channels_json(self, tmp_path):
        from insightbot.migrate import migrate_from_v1
        from insightbot.config import load_channels

        # Create minimal v1 config files
        config_dir = tmp_path / "bot"
        config_dir.mkdir()
        (config_dir / "config.content.json").write_text(json.dumps({
            "feeds": {},
            "search": {},
        }))
        (config_dir / "config.secrets.json").write_text(json.dumps({
            "wecom": {
                "cid": "test_cid",
                "secret": "test_secret",
                "aid": "12345",
            }
        }))

        with patch("insightbot.migrate.load_runtime_config") as mock_load:
            mock_load.return_value = {
                "feeds": {},
                "wecom": {"cid": "test_cid", "secret": "test_secret", "aid": "12345"},
                "search": {},
            }
            migrate_from_v1(str(config_dir))

        channels = load_channels(str(config_dir))
        assert "channels" in channels
        assert "wecom_main" in channels["channels"]
        ch = channels["channels"]["wecom_main"]
        assert ch["cid"] == "test_cid"
        assert ch["secret"] == "test_secret"
        assert ch["agent_id"] == "12345"

    def test_creates_tasks_json(self, tmp_path):
        from insightbot.migrate import migrate_from_v1
        from insightbot.config import load_tasks

        config_dir = tmp_path / "bot"
        config_dir.mkdir()
        (config_dir / "config.content.json").write_text(json.dumps({
            "feeds": {
                "💡 营销行业": {"rss": ["http://example.com/rss"]}
            },
            "search": {"enabled": False},
        }))
        (config_dir / "config.secrets.json").write_text(json.dumps({
            "wecom": {"cid": "c", "secret": "s", "aid": "1"}
        }))

        with patch("insightbot.migrate.load_runtime_config") as mock_load:
            mock_load.return_value = {
                "feeds": {"💡 营销行业": {"rss": ["http://example.com/rss"]}},
                "wecom": {"cid": "c", "secret": "s", "aid": "1"},
                "search": {"enabled": False},
                "ai": {
                    "editorial_pipeline": {
                        "enabled": True,
                        "global_shortlist_multiplier": 3,
                        "allow_multi_assign": False,
                    }
                },
            }
            migrate_from_v1(str(config_dir))

        tasks = load_tasks(str(config_dir))
        assert "tasks" in tasks
        assert "daily_brief" in tasks["tasks"]
        task = tasks["tasks"]["daily_brief"]
        assert task["name"] == "每日营销早报"
        assert task["enabled"] is True
        assert task["pipeline"] == "editorial"
        assert task["channels"] == ["wecom_main"]
        assert task["sources"]["rss"][0]["url"] == "http://example.com/rss"
        assert "💡 营销行业" in task["sections"]

    def test_skips_when_files_exist(self, tmp_path):
        from insightbot.migrate import migrate_from_v1

        config_dir = tmp_path / "bot"
        config_dir.mkdir()
        (config_dir / "channels.json").write_text(json.dumps({"channels": {}}))
        (config_dir / "tasks.json").write_text(json.dumps({"tasks": {}}))

        with patch("insightbot.migrate.load_runtime_config") as mock_load:
            migrate_from_v1(str(config_dir))
            # load_runtime_config should NOT be called if files exist
            mock_load.assert_not_called()
