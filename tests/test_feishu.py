"""
test_feishu.py — insightbot.feishu 模块单元测试
"""

from unittest.mock import MagicMock, patch

from insightbot.feishu import send_text_to_bot


def _mock_post_response(data: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = data
    return response


class TestSendTextToBot:
    def test_returns_true_on_success(self):
        with patch("insightbot.feishu.requests.post", return_value=_mock_post_response({"code": 0})):
            assert send_text_to_bot(webhook_url="https://open.feishu.cn/webhook/ok", content="hello") is True

    def test_returns_false_when_webhook_missing(self):
        assert send_text_to_bot(webhook_url="", content="hello") is False

    def test_returns_false_on_api_error(self):
        with patch("insightbot.feishu.requests.post", return_value=_mock_post_response({"code": 19024})):
            assert send_text_to_bot(webhook_url="https://open.feishu.cn/webhook/fail", content="hello") is False

    def test_appends_mention_all(self):
        with patch("insightbot.feishu.requests.post", return_value=_mock_post_response({"code": 0})) as mock_post:
            send_text_to_bot(
                webhook_url="https://open.feishu.cn/webhook/ok",
                content="hello",
                mention_all=True,
            )

        payload = mock_post.call_args.kwargs["json"]
        assert "<at user_id=\"all\">所有人</at>" in payload["content"]["text"]
