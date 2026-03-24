import json
import os
import re


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
