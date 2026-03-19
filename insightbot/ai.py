import requests


def chat_completion(
    *,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    temperature: float = 0.1,
    timeout_s: int = 120,
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
    resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout_s)
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

