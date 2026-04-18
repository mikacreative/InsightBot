"""
test_config_paths.py — insightbot.paths 和 insightbot.config 模块测试

测试范围：
  - default_bot_dir() 的路径优先级（环境变量 > /root/marketing_bot > 仓库目录）
  - config_file_path()、bot_log_file_path() 的路径拼接逻辑
  - load_json_config() 的正常加载与文件不存在时的异常
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from insightbot.paths import (
    default_bot_dir,
    data_dir,
    config_content_file_path,
    config_file_path,
    config_secrets_file_path,
    bot_log_file_path,
    feed_health_cache_file_path,
    logs_dir,
    task_health_cache_file_path,
    task_runs_file_path,
    task_state_file_path,
)
from insightbot.config import load_json_config, load_runtime_config


# ── default_bot_dir 测试 ──────────────────────────────────────────────────────
class TestDefaultBotDir:

    def test_env_var_takes_highest_priority(self, tmp_path):
        """MARKETING_BOT_DIR 环境变量应具有最高优先级。"""
        custom_dir = str(tmp_path / "custom_bot_dir")
        with patch.dict(os.environ, {"MARKETING_BOT_DIR": custom_dir}):
            result = default_bot_dir()
        assert result == custom_dir

    def test_falls_back_to_repo_root_when_no_env_and_no_server_path(self):
        """无环境变量且 /root/marketing_bot 不存在时，应回退到仓库根目录。"""
        env_without_dir = {k: v for k, v in os.environ.items() if k != "MARKETING_BOT_DIR"}
        with patch.dict(os.environ, env_without_dir, clear=True):
            with patch("insightbot.paths.os.path.isdir", return_value=False):
                result = default_bot_dir()
        # 应返回一个绝对路径
        assert os.path.isabs(result)


# ── config_file_path 测试 ─────────────────────────────────────────────────────
class TestConfigFilePath:

    def test_env_var_overrides_default(self, tmp_path):
        """CONFIG_FILE 环境变量应覆盖默认的 config.json 路径。"""
        custom_path = str(tmp_path / "my_config.json")
        with patch.dict(os.environ, {"CONFIG_FILE": custom_path}):
            result = config_file_path()
        assert result == custom_path

    def test_default_path_is_config_json_in_bot_dir(self, tmp_path):
        """无环境变量时，应返回 bot_dir/config.json。"""
        env_without = {k: v for k, v in os.environ.items()
                       if k not in ("CONFIG_FILE", "MARKETING_BOT_DIR")}
        with patch.dict(os.environ, env_without, clear=True):
            with patch("insightbot.paths.default_bot_dir", return_value=str(tmp_path)):
                result = config_file_path(str(tmp_path))
        assert result == str(tmp_path / "config.json")


class TestSplitConfigPaths:

    def test_content_path_defaults_to_config_content_json(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("CONFIG_CONTENT_FILE", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = config_content_file_path(str(tmp_path))
        assert result == str(tmp_path / "config.content.json")

    def test_secrets_path_defaults_to_config_secrets_json(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("CONFIG_SECRETS_FILE", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = config_secrets_file_path(str(tmp_path))
        assert result == str(tmp_path / "config.secrets.json")

    def test_data_dir_defaults_to_data_subdir(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("DATA_DIR", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = data_dir(str(tmp_path))
        assert result == str(tmp_path / "data")

    def test_feed_health_cache_path_defaults_to_data_dir(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("FEED_HEALTH_CACHE_FILE", "DATA_DIR", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = feed_health_cache_file_path(str(tmp_path))
        assert result == str(tmp_path / "data" / "feed_health_cache.json")

    def test_task_runs_path_defaults_to_data_dir(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("TASK_RUNS_FILE", "DATA_DIR", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = task_runs_file_path(str(tmp_path))
        assert result == str(tmp_path / "data" / "task_runs.jsonl")

    def test_task_health_cache_path_defaults_to_task_health_subdir(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("TASK_HEALTH_CACHE_FILE", "DATA_DIR", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = task_health_cache_file_path("daily_brief", str(tmp_path))
        assert result == str(tmp_path / "data" / "task_health" / "daily_brief.json")

    def test_task_state_path_defaults_to_task_state_subdir(self, tmp_path):
        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("TASK_STATE_FILE", "DATA_DIR", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = task_state_file_path("daily_brief", str(tmp_path))
        assert result == str(tmp_path / "data" / "task_state" / "daily_brief.json")


# ── bot_log_file_path 测试 ────────────────────────────────────────────────────
class TestBotLogFilePath:

    def test_env_var_overrides_default(self, tmp_path):
        """BOT_LOG_FILE 环境变量应覆盖默认的日志路径。"""
        custom_log = str(tmp_path / "custom_bot.log")
        with patch.dict(os.environ, {"BOT_LOG_FILE": custom_log}):
            result = bot_log_file_path()
        assert result == custom_log

    def test_default_path_is_in_logs_subdir(self, tmp_path):
        """无环境变量时，日志文件应位于 bot_dir/logs/bot.log。"""
        env_without = {k: v for k, v in os.environ.items()
                       if k not in ("BOT_LOG_FILE", "LOGS_DIR", "MARKETING_BOT_DIR")}
        with patch.dict(os.environ, env_without, clear=True):
            result = bot_log_file_path(str(tmp_path))
        assert result == str(tmp_path / "logs" / "bot.log")


# ── load_json_config 测试 ─────────────────────────────────────────────────────
class TestLoadJsonConfig:

    def test_loads_valid_config(self, tmp_path):
        """应正确加载并解析有效的 JSON 配置文件。"""
        config_data = {
            "wecom": {"cid": "test", "secret": "s", "aid": "1"},
            "ai": {"model": "gpt-4"},
            "feeds": {},
            "settings": {}
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        result = load_json_config(str(config_file))
        assert result["wecom"]["cid"] == "test"
        assert result["ai"]["model"] == "gpt-4"

    def test_raises_on_missing_file(self, tmp_path):
        """配置文件不存在时应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_json_config(str(tmp_path / "nonexistent.json"))

    def test_raises_on_invalid_json(self, tmp_path):
        """配置文件内容不是合法 JSON 时应抛出 json.JSONDecodeError。"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ this is not valid json }", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_json_config(str(bad_file))

    def test_preserves_unicode(self, tmp_path):
        """配置文件中的中文字符应被正确读取，不出现乱码。"""
        config_data = {"settings": {"report_title": "📅 营销情报早报 | {date}"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        result = load_json_config(str(config_file))
        assert result["settings"]["report_title"] == "📅 营销情报早报 | {date}"


class TestLoadRuntimeConfig:

    def test_prefers_split_config_and_merges_secrets(self, tmp_path):
        content = {
            "ai": {"system_prompt": "sys"},
            "feeds": {"营销": {"rss": ["https://example.com/feed"], "keywords": [], "prompt": "筛选"}},
            "settings": {"report_title": "日报"},
        }
        secrets = {
            "wecom": {"cid": "cid", "secret": "secret", "aid": "10001"},
            "ai": {"api_key": "secret-key", "api_url": "https://api.example.com", "model": "kimi"},
        }
        (tmp_path / "config.content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "config.secrets.json").write_text(json.dumps(secrets, ensure_ascii=False), encoding="utf-8")

        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("CONFIG_FILE", "CONFIG_CONTENT_FILE", "CONFIG_SECRETS_FILE", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = load_runtime_config(str(tmp_path))

        assert result["ai"]["model"] == "kimi"
        assert result["ai"]["api_key"] == "secret-key"
        assert result["wecom"]["cid"] == "cid"
        assert "营销" in result["feeds"]

    def test_falls_back_to_legacy_single_file(self, tmp_path):
        legacy = {
            "wecom": {"cid": "cid"},
            "ai": {"api_key": "key", "model": "legacy-model"},
            "feeds": {},
            "settings": {},
        }
        (tmp_path / "config.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        env_without = {
            k: v for k, v in os.environ.items()
            if k not in ("CONFIG_FILE", "CONFIG_CONTENT_FILE", "CONFIG_SECRETS_FILE", "MARKETING_BOT_DIR")
        }
        with patch.dict(os.environ, env_without, clear=True):
            result = load_runtime_config(str(tmp_path))

        assert result["ai"]["model"] == "legacy-model"
        assert result["ai"]["api_key"] == "key"

    def test_env_vars_override_split_files(self, tmp_path):
        content = {"ai": {"model": "kimi"}, "feeds": {}, "settings": {}}
        secrets = {"ai": {"api_key": "file-key"}}
        (tmp_path / "config.content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "config.secrets.json").write_text(json.dumps(secrets, ensure_ascii=False), encoding="utf-8")

        with patch.dict(
            os.environ,
            {
                "AI_API_KEY": "env-key",
                "AI_API_URL": "https://env.example.com",
            },
            clear=False,
        ):
            result = load_runtime_config(str(tmp_path))

        assert result["ai"]["api_key"] == "env-key"
        assert result["ai"]["api_url"] == "https://env.example.com"
