"""
test_wecom.py — insightbot.wecom 模块单元测试

测试范围：
  - get_access_token() 正常获取与失败处理
  - send_markdown_to_app() 的 payload 结构验证
  - Token 获取失败时 send 函数应返回 False
  - 网络异常时的静默处理（不抛出异常）
"""
import pytest
from unittest.mock import patch, MagicMock

from insightbot.wecom import get_access_token, send_markdown_to_app


# ── 辅助：构造 mock 响应 ──────────────────────────────────────────────────────
def _mock_get_response(data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = data
    return m


def _mock_post_response(data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = data
    return m


# ── get_access_token 测试 ─────────────────────────────────────────────────────
class TestGetAccessToken:

    def test_returns_token_on_success(self):
        """errcode=0 时应返回 access_token 字符串。"""
        mock_resp = _mock_get_response({"errcode": 0, "access_token": "mock_token_xyz"})
        with patch("insightbot.wecom.requests.get", return_value=mock_resp):
            token = get_access_token("test_cid", "test_secret")
        assert token == "mock_token_xyz"

    def test_returns_none_on_api_error(self):
        """API 返回非 0 errcode 时应返回 None。"""
        mock_resp = _mock_get_response({"errcode": 40013, "errmsg": "invalid corpid"})
        with patch("insightbot.wecom.requests.get", return_value=mock_resp):
            token = get_access_token("bad_cid", "bad_secret")
        assert token is None

    def test_returns_none_on_network_exception(self):
        """网络异常时应静默返回 None，不抛出异常。"""
        with patch("insightbot.wecom.requests.get", side_effect=Exception("network error")):
            token = get_access_token("cid", "secret")
        assert token is None

    def test_request_url_contains_credentials(self):
        """请求 URL 必须包含 corpid 和 corpsecret 参数。"""
        mock_resp = _mock_get_response({"errcode": 0, "access_token": "tok"})
        with patch("insightbot.wecom.requests.get", return_value=mock_resp) as mock_get:
            get_access_token("my_corp_id", "my_corp_secret")
        call_url = mock_get.call_args[0][0]
        assert "my_corp_id" in call_url
        assert "my_corp_secret" in call_url


# ── send_markdown_to_app 测试 ─────────────────────────────────────────────────
class TestSendMarkdownToApp:

    def test_returns_true_on_success(self):
        """Token 获取成功且推送成功时应返回 True。"""
        with patch("insightbot.wecom.get_access_token", return_value="valid_token"):
            mock_post = _mock_post_response({"errcode": 0, "errmsg": "ok"})
            with patch("insightbot.wecom.requests.post", return_value=mock_post):
                result = send_markdown_to_app(
                    cid="cid", secret="secret", agent_id="1000001",
                    content="# 测试消息\n这是一条测试推送。"
                )
        assert result is True

    def test_returns_false_when_token_fails(self):
        """Token 获取失败时应直接返回 False，不尝试推送。"""
        with patch("insightbot.wecom.get_access_token", return_value=None):
            with patch("insightbot.wecom.requests.post") as mock_post:
                result = send_markdown_to_app(
                    cid="cid", secret="secret", agent_id="1000001",
                    content="测试"
                )
        assert result is False
        mock_post.assert_not_called()

    def test_payload_structure(self):
        """推送 payload 必须包含正确的 msgtype、agentid 和 markdown 字段。"""
        with patch("insightbot.wecom.get_access_token", return_value="tok"):
            mock_post_resp = _mock_post_response({"errcode": 0})
            with patch("insightbot.wecom.requests.post", return_value=mock_post_resp) as mock_post:
                send_markdown_to_app(
                    cid="cid", secret="secret", agent_id="2000002",
                    content="## 板块标题\n内容摘要"
                )
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["msgtype"] == "markdown"
        assert payload["agentid"] == "2000002"
        assert payload["markdown"]["content"] == "## 板块标题\n内容摘要"
        assert payload["touser"] == "@all"
        assert payload["safe"] == 0

    def test_returns_false_on_api_error_response(self):
        """企业微信 API 返回非 0 errcode 时应返回 False。"""
        with patch("insightbot.wecom.get_access_token", return_value="tok"):
            mock_post_resp = _mock_post_response({"errcode": 60020, "errmsg": "not allow"})
            with patch("insightbot.wecom.requests.post", return_value=mock_post_resp):
                result = send_markdown_to_app(
                    cid="cid", secret="secret", agent_id="1000001",
                    content="测试"
                )
        assert result is False

    def test_returns_false_on_network_exception(self):
        """推送时网络异常应静默返回 False，不抛出异常。"""
        with patch("insightbot.wecom.get_access_token", return_value="tok"):
            with patch("insightbot.wecom.requests.post", side_effect=Exception("timeout")):
                result = send_markdown_to_app(
                    cid="cid", secret="secret", agent_id="1000001",
                    content="测试"
                )
        assert result is False
