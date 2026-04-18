import json
import re

import requests


def get_tenant_access_token(
    *,
    app_id: str,
    app_secret: str,
    timeout_s: int = 10,
) -> str | None:
    if not app_id or not app_secret:
        return None

    try:
        response = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=timeout_s,
        )
        data = response.json()
    except Exception:
        return None

    if data.get("code") != 0:
        return None
    return data.get("tenant_access_token")


def _strip_markdown_for_text(content: str) -> str:
    text = re.sub(r"^#+\s*", "", content, flags=re.MULTILINE)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1: \2", text)
    return text.strip()


def build_interactive_card(*, title: str, markdown: str) -> dict:
    sections = [block.strip() for block in re.split(r"\n{2,}", markdown) if block.strip()]
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": section,
            },
        }
        for section in sections[:12]
    ] or [
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": "暂无内容",
            },
        }
    ]

    return {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": title,
            },
        },
        "elements": elements,
    }


def send_message(
    *,
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    msg_type: str,
    content: dict,
    timeout_s: int = 10,
) -> bool:
    token = get_tenant_access_token(app_id=app_id, app_secret=app_secret, timeout_s=timeout_s)
    if not token:
        return False

    try:
        response = requests.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
            timeout=timeout_s,
        )
        data = response.json()
    except Exception:
        return False

    return data.get("code") == 0


def send_text_message(
    *,
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    content: str,
    timeout_s: int = 10,
) -> bool:
    return send_message(
        app_id=app_id,
        app_secret=app_secret,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        msg_type="text",
        content={"text": _strip_markdown_for_text(content)},
        timeout_s=timeout_s,
    )


def send_interactive_message(
    *,
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    title: str,
    markdown: str,
    timeout_s: int = 10,
) -> bool:
    return send_message(
        app_id=app_id,
        app_secret=app_secret,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        msg_type="interactive",
        content=build_interactive_card(title=title, markdown=markdown),
        timeout_s=timeout_s,
    )
