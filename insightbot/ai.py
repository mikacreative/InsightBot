import requests
from typing import Optional


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
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
