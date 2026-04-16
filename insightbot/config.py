import json
import os
import re
from copy import deepcopy

from .paths import (
    channels_file_path,
    config_content_file_path,
    config_file_path,
    config_secrets_file_path,
    default_bot_dir,
    tasks_file_path,
)


def _replace_env_vars(data):
    """
    递归遍历字典或列表，将字符串中的 ${VAR_NAME} 替换为对应的环境变量值。
    如果环境变量不存在，则保留原样。
    """
    if isinstance(data, dict):
        return {k: _replace_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_replace_env_vars(i) for i in data]
    elif isinstance(data, str):
        # 使用正则匹配 ${VAR_NAME} 格式
        pattern = re.compile(r"\$\{(\w+)\}")

        def replacer(match):
            env_var = match.group(1)
            # 优先从环境变量获取，若无则返回原占位符
            return os.getenv(env_var, match.group(0))

        return pattern.sub(replacer, data)
    return data


def load_json_config(path: str) -> dict:
    """
    加载 JSON 配置文件，并自动替换其中的环境变量占位符。
    """
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # 执行环境变量替换
    return _replace_env_vars(config)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 中的值优先。"""
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _env_runtime_overrides() -> dict:
    """从环境变量收集运行时覆盖项，兼容 secrets 文件缺失的场景。"""
    overrides = {
        "wecom": {},
        "ai": {},
    }

    env_map = {
        "wecom": {
            "cid": "WECOM_CID",
            "secret": "WECOM_SECRET",
            "aid": "WECOM_AID",
        },
        "ai": {
            "api_key": "AI_API_KEY",
            "api_url": "AI_API_URL",
            "model": "AI_MODEL",
        },
    }

    for section, mappings in env_map.items():
        for key, env_name in mappings.items():
            value = os.getenv(env_name)
            if value:
                overrides[section][key] = value

    return {k: v for k, v in overrides.items() if v}


def load_runtime_config(bot_dir: str | None = None) -> dict:
    """
    加载运行时配置。

    优先级：
    1. 显式指定的 CONFIG_FILE（旧版单文件）
    2. config.content.json + config.secrets.json（推荐）
    3. 旧版 config.json
    4. 环境变量覆盖文件中的敏感配置
    """
    bot_dir = bot_dir or default_bot_dir()

    explicit_legacy_path = os.getenv("CONFIG_FILE")
    if explicit_legacy_path:
        config = load_json_config(explicit_legacy_path)
        return _deep_merge(config, _env_runtime_overrides())

    content_path = config_content_file_path(bot_dir)
    secrets_path = config_secrets_file_path(bot_dir)
    legacy_path = config_file_path(bot_dir)

    if os.path.exists(content_path):
        config = load_json_config(content_path)
        if os.path.exists(secrets_path):
            config = _deep_merge(config, load_json_config(secrets_path))
    elif os.path.exists(legacy_path):
        config = load_json_config(legacy_path)
    else:
        raise FileNotFoundError(
            f"未找到配置文件。请提供 {content_path}（推荐）或 {legacy_path}（兼容旧版）。"
        )

    return _deep_merge(config, _env_runtime_overrides())


def load_channels(bot_dir: str | None = None) -> dict:
    """Load channels.json. Returns {"channels": {}} if file does not exist."""
    bot_dir = bot_dir or default_bot_dir()
    path = channels_file_path(bot_dir)
    if not os.path.exists(path):
        return {"channels": {}}
    return load_json_config(path)


def save_channels(channels: dict, bot_dir: str | None = None) -> None:
    """Atomically write channels.json."""
    bot_dir = bot_dir or default_bot_dir()
    path = channels_file_path(bot_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


def load_tasks(bot_dir: str | None = None) -> dict:
    """Load tasks.json. Returns {"tasks": {}} if file does not exist."""
    bot_dir = bot_dir or default_bot_dir()
    path = tasks_file_path(bot_dir)
    if not os.path.exists(path):
        return {"tasks": {}}
    return load_json_config(path)


def save_tasks(tasks: dict, bot_dir: str | None = None) -> None:
    """Atomically write tasks.json."""
    bot_dir = bot_dir or default_bot_dir()
    path = tasks_file_path(bot_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


def load_tasks_config(task_id: str, bot_dir: str | None = None) -> dict:
    """
    Assemble a full runtime config for a specific task.
    Merges base config (AI, secrets, settings) with task-level feeds and pipeline_config.
    Raises KeyError if task not found.
    """
    bot_dir = bot_dir or default_bot_dir()
    base = load_runtime_config(bot_dir)
    tasks_data = load_tasks(bot_dir)
    tasks_map = tasks_data.get("tasks", {})
    if task_id not in tasks_map:
        raise KeyError(f"Task '{task_id}' not found in tasks.json")
    task_def = tasks_map[task_id]

    # Start from base config
    config = deepcopy(base)

    # Merge task-level feeds (replaces global feeds)
    feeds = task_def.get("feeds", {})
    if feeds:
        config["feeds"] = deepcopy(feeds)

    # Merge pipeline_config into ai section
    pipeline_config = task_def.get("pipeline_config", {})
    if pipeline_config:
        ai = config.setdefault("ai", {})
        editorial = ai.setdefault("editorial_pipeline", {})
        editorial.update(deepcopy(pipeline_config))

    # Merge search if present in task
    search = task_def.get("search", {})
    if search:
        config["search"] = deepcopy(search)

    # Inject task's channels list so task_runner can read it
    config["_task_channels"] = list(task_def.get("channels", []))

    # Inject pipeline type
    config["_task_pipeline"] = task_def.get("pipeline", "editorial")

    return config
