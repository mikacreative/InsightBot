import requests


def send_text_to_bot(
    *,
    webhook_url: str,
    content: str,
    timeout_s: int = 10,
    mention_all: bool = False,
) -> bool:
    if not webhook_url:
        return False

    text = content
    if mention_all:
        text = f"{content}\n<at user_id=\"all\">所有人</at>"

    payload = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=timeout_s)
        data = response.json()
    except Exception:
        return False

    return data.get("code", 0) == 0
