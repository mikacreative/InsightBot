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


def _normalize_search_queries(search_payload: dict | None) -> dict:
    search_payload = deepcopy(search_payload or {})
    normalized_queries = []
    for item in search_payload.get("queries", []) or []:
        if isinstance(item, str):
            keywords = item.strip()
            if not keywords:
                continue
            normalized_queries.append(
                {"keywords": keywords, "section_hints": [], "max_results": 10}
            )
            continue

        if not isinstance(item, dict):
            continue

        keywords = str(item.get("keywords", "")).strip()
        if not keywords:
            continue

        section_hints = item.get("section_hints")
        if section_hints is None:
            legacy_hint = str(item.get("category_hint", "")).strip()
            section_hints = [legacy_hint] if legacy_hint else []
        elif isinstance(section_hints, str):
            section_hints = [section_hints.strip()] if section_hints.strip() else []
        else:
            section_hints = [str(v).strip() for v in section_hints if str(v).strip()]

        normalized_queries.append(
            {
                "keywords": keywords,
                "section_hints": section_hints,
                "max_results": int(item.get("max_results", 10) or 10),
            }
        )

    search_payload["queries"] = normalized_queries
    return search_payload


def derive_sections_from_feeds(feeds: dict | None) -> dict:
    sections: dict[str, dict] = {}
    for category, feed_data in (feeds or {}).items():
        payload = feed_data or {}
        sections[category] = {
            "prompt": str(payload.get("prompt", "")).strip(),
            "keywords": [str(v).strip() for v in payload.get("keywords", []) if str(v).strip()],
            "source_hints": [str(category).strip()] if str(category).strip() else [],
        }
    return sections


def derive_sources_from_feeds_and_search(feeds: dict | None, search: dict | None) -> dict:
    rss_items: list[dict] = []
    seen_urls: set[str] = set()
    for category, feed_data in (feeds or {}).items():
        for raw_url in (feed_data or {}).get("rss", []) or []:
            raw_text = str(raw_url).strip()
            if not raw_text:
                continue
            url = raw_text.split("#")[0].strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            source_id = re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_").lower() or f"rss_{len(rss_items)+1}"
            rss_items.append(
                {
                    "id": source_id[:80],
                    "url": raw_text,
                    "enabled": True,
                    "tags": [str(category).strip()] if str(category).strip() else [],
                }
            )

    return {
        "rss": rss_items,
        "search": _normalize_search_queries(search),
    }


def derive_feeds_from_sources_and_sections(sources: dict | None, sections: dict | None) -> dict:
    sections = deepcopy(sections or {})
    rss_entries = list((sources or {}).get("rss", []) or [])
    search_cfg = _normalize_search_queries((sources or {}).get("search", {}))

    feeds: dict[str, dict] = {}
    section_names = list(sections.keys())
    for section_name, section_data in sections.items():
        feeds[section_name] = {
            "rss": [],
            "keywords": [str(v).strip() for v in (section_data or {}).get("keywords", []) if str(v).strip()],
            "prompt": str((section_data or {}).get("prompt", "")).strip(),
        }

    for source in rss_entries:
        if not isinstance(source, dict):
            continue
        raw_url = str(source.get("url", "")).strip()
        if not raw_url:
            continue
        target_sections = [str(v).strip() for v in source.get("section_hints", []) if str(v).strip()]
        target_sections = [s for s in target_sections if s in feeds]
        if not target_sections:
            source_tags = [str(v).strip() for v in source.get("tags", []) if str(v).strip()]
            for section_name, section_data in sections.items():
                hints = [str(v).strip() for v in (section_data or {}).get("source_hints", []) if str(v).strip()]
                if source_tags and set(source_tags) & set(hints):
                    target_sections.append(section_name)
        if not target_sections and section_names:
            target_sections = [section_names[0]]

        for section_name in target_sections:
            feeds.setdefault(section_name, {"rss": [], "keywords": [], "prompt": ""})
            if raw_url not in feeds[section_name]["rss"]:
                feeds[section_name]["rss"].append(raw_url)

    for query in search_cfg.get("queries", []) or []:
        for hint in query.get("section_hints", []) or []:
            if hint in feeds:
                for keyword in str(query.get("keywords", "")).split():
                    keyword = keyword.strip()
                    if keyword and keyword not in feeds[hint]["keywords"]:
                        feeds[hint]["keywords"].append(keyword)

    return feeds


def normalize_task_definition(task_def: dict | None) -> dict:
    task_def = deepcopy(task_def or {})
    if task_def.get("sources") or task_def.get("sections"):
        task_def["sources"] = {
            "rss": deepcopy((task_def.get("sources", {}) or {}).get("rss", []) or []),
            "search": _normalize_search_queries((task_def.get("sources", {}) or {}).get("search", {})),
        }
        task_def["sections"] = deepcopy(task_def.get("sections", {}) or {})
        task_def.pop("feeds", None)
        task_def.pop("search", None)
        return task_def

    feeds = deepcopy(task_def.get("feeds", {}) or {})
    search = deepcopy(task_def.get("search", {}) or {})
    task_def["sources"] = derive_sources_from_feeds_and_search(feeds, search)
    task_def["sections"] = derive_sections_from_feeds(feeds)
    task_def.pop("feeds", None)
    task_def.pop("search", None)
    return task_def


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
    task_def = normalize_task_definition(tasks_map[task_id])

    # Start from base config
    config = deepcopy(base)

    sources = deepcopy(task_def.get("sources", {}) or {})
    sections = deepcopy(task_def.get("sections", {}) or {})
    if sources:
        config["sources"] = sources
        config["search"] = deepcopy(sources.get("search", {}))
    if sections:
        config["sections"] = sections
    if sources or sections:
        config["feeds"] = derive_feeds_from_sources_and_sections(sources, sections)

    # Merge pipeline_config into ai section
    pipeline_config = task_def.get("pipeline_config", {})
    if pipeline_config:
        ai = config.setdefault("ai", {})
        editorial = ai.setdefault("editorial_pipeline", {})
        editorial.update(deepcopy(pipeline_config))

    # Inject task's channels list so task_runner can read it
    config["_task_channels"] = list(task_def.get("channels", []))

    # Inject pipeline type
    config["_task_pipeline"] = task_def.get("pipeline", "editorial")

    # Inject editorial pipeline mode ("legacy" | "editorial-intelligence")
    config["_editorial_pipeline_mode"] = task_def.get("_editorial_pipeline_mode", "legacy")

    # Inject task metadata for status/history layers
    config["_task_name"] = task_def.get("name", task_id)

    return config
