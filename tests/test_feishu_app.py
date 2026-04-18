"""
test_feishu_app.py — insightbot.feishu_app 模块单元测试
"""

import json
from unittest.mock import MagicMock, patch

from insightbot.feishu_app import build_interactive_card, get_tenant_access_token, send_interactive_message, send_text_message


def _mock_response(data: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = data
    return response


class TestTenantAccessToken:
    def test_returns_token_on_success(self):
        with patch("insightbot.feishu_app.requests.post", return_value=_mock_response({"code": 0, "tenant_access_token": "t-123"})):
            assert get_tenant_access_token(app_id="cli", app_secret="secret") == "t-123"

    def test_returns_none_on_failure(self):
        with patch("insightbot.feishu_app.requests.post", return_value=_mock_response({"code": 999})):
            assert get_tenant_access_token(app_id="cli", app_secret="secret") is None


class TestCardBuilder:
    def test_build_interactive_card_contains_header_and_elements(self):
        card = build_interactive_card(title="日报", markdown="## 标题\n\n正文")
        assert card["header"]["title"]["content"] == "日报"
        assert len(card["elements"]) == 2


class TestFeishuAppSend:
    def test_send_text_message_uses_text_payload(self):
        with patch("insightbot.feishu_app.get_tenant_access_token", return_value="token"):
            with patch("insightbot.feishu_app.requests.post", return_value=_mock_response({"code": 0})) as mock_post:
                assert send_text_message(
                    app_id="cli",
                    app_secret="secret",
                    receive_id="chat-id",
                    receive_id_type="chat_id",
                    content="## 报告",
                ) is True

        payload = mock_post.call_args.kwargs["json"]
        assert payload["msg_type"] == "text"
        assert "报告" in json.loads(payload["content"])["text"]

    def test_send_interactive_message_uses_card_payload(self):
        with patch("insightbot.feishu_app.get_tenant_access_token", return_value="token"):
            with patch("insightbot.feishu_app.requests.post", return_value=_mock_response({"code": 0})) as mock_post:
                assert send_interactive_message(
                    app_id="cli",
                    app_secret="secret",
                    receive_id="chat-id",
                    receive_id_type="chat_id",
                    title="日报",
                    markdown="## 标题\n\n正文",
                ) is True

        payload = mock_post.call_args.kwargs["json"]
        assert payload["msg_type"] == "interactive"
        card = json.loads(payload["content"])
        assert card["header"]["title"]["content"] == "日报"
