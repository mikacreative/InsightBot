import requests
from typing import Optional


def get_access_token(cid: str, secret: str, timeout_s: int = 10) -> Optional[str]:
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={cid}&corpsecret={secret}"
    )
    try:
        data = requests.get(url, timeout=timeout_s).json()
        if data.get("errcode") == 0:
            return data.get("access_token")
        return None
    except Exception:
        return None


def send_markdown_to_app(
    *,
    cid: str,
    secret: str,
    agent_id: str,
    content: str,
    touser: str = "@all",
    timeout_s: int = 10,
) -> bool:
    token = get_access_token(cid, secret, timeout_s=timeout_s)
    if not token:
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": touser,
        "msgtype": "markdown",
        "agentid": agent_id,
        "markdown": {"content": content},
        "safe": 0,
    }
    try:
        res = requests.post(url, json=payload, timeout=timeout_s).json()
        return res.get("errcode") == 0
    except Exception:
        return False

