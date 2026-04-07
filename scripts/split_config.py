#!/usr/bin/env python3
"""
split_config.py — 将旧版单文件 config.json 拆分为 content + secrets

用法：
  python3 scripts/split_config.py \
    --input /root/marketing_bot/config.json \
    --content-out /root/marketing_bot/config.content.json \
    --secrets-out /root/marketing_bot/config.secrets.json
"""
import argparse
import json
from copy import deepcopy
from pathlib import Path


AI_URL_PLACEHOLDER = "${AI_API_URL}"
AI_MODEL_PLACEHOLDER = "${AI_MODEL}"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
        f.write("\n")


def split_legacy_config(legacy: dict) -> tuple[dict, dict]:
    content = deepcopy(legacy)
    secrets: dict = {}

    wecom = deepcopy(legacy.get("wecom", {}))
    if wecom:
        secrets["wecom"] = wecom
        content.pop("wecom", None)

    ai_in = deepcopy(legacy.get("ai", {}))
    if ai_in:
        content_ai = deepcopy(ai_in)
        content_ai["api_url"] = AI_URL_PLACEHOLDER
        content_ai["model"] = AI_MODEL_PLACEHOLDER
        content_ai.pop("api_key", None)
        content["ai"] = content_ai

        api_key = ai_in.get("api_key")
        if api_key:
            secrets.setdefault("ai", {})
            secrets["ai"]["api_key"] = api_key

    return content, secrets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拆分旧版 config.json 为 content/secrets 双层配置")
    parser.add_argument("--input", required=True, help="旧版 config.json 路径")
    parser.add_argument("--content-out", required=True, help="输出的 config.content.json 路径")
    parser.add_argument("--secrets-out", required=True, help="输出的 config.secrets.json 路径")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    content_out = Path(args.content_out).expanduser().resolve()
    secrets_out = Path(args.secrets_out).expanduser().resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"找不到输入文件: {input_path}")

    for out_path in (content_out, secrets_out):
        if out_path.exists() and not args.force:
            raise FileExistsError(f"输出文件已存在，请先备份或使用 --force 覆盖: {out_path}")

    legacy = load_json(input_path)
    content, secrets = split_legacy_config(legacy)

    content_out.parent.mkdir(parents=True, exist_ok=True)
    secrets_out.parent.mkdir(parents=True, exist_ok=True)

    dump_json(content_out, content)
    dump_json(secrets_out, secrets)

    print("拆分完成：")
    print(f"  content -> {content_out}")
    print(f"  secrets -> {secrets_out}")
    print("后续请补充环境变量：AI_API_URL / AI_MODEL")


if __name__ == "__main__":
    main()
