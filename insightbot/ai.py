import json
from typing import Optional

import requests


def _response_preview(resp: requests.Response, limit: int = 300) -> str:
    text = (resp.text or "").strip()
    if not text:
        return "<empty>"
    return text[:limit].replace("\n", "\\n")


def chat_completion(
    *,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    temperature: float = 0.1,
    timeout_s: int = 120,
    json_mode: bool = False,
    json_schema: Optional[dict] = None,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": temperature,
    }
    if json_mode:
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
        else:
            payload["response_format"] = {"type": "json_object"}
    resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout_s)
    try:
        data = resp.json()
    except ValueError as exc:
        content_type = resp.headers.get("Content-Type", "unknown")
        preview = _response_preview(resp)
        raise ValueError(
            f"AI API 返回了非 JSON 响应，HTTP {resp.status_code}，Content-Type: {content_type}，Body: {preview}"
        ) from exc

    if resp.status_code >= 400:
        detail = data.get("error") if isinstance(data, dict) else data
        if isinstance(detail, dict):
            detail_text = detail.get("message") or json.dumps(detail, ensure_ascii=False)
        else:
            detail_text = str(detail)
        raise RuntimeError(f"AI API 请求失败，HTTP {resp.status_code}: {detail_text or '未知错误'}")

    if not isinstance(data, dict) or "choices" not in data:
        detail_text = json.dumps(data, ensure_ascii=False)[:500]
        raise KeyError(f'AI API 响应缺少 "choices" 字段: {detail_text}')

    choices = data["choices"]
    if not isinstance(choices, list) or not choices:
        raise KeyError('AI API 响应中的 "choices" 为空')

    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise KeyError('AI API 响应中的 "message.content" 缺失或不是字符串')

    return content.strip()
