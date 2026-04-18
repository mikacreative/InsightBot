"""
test_ai.py — insightbot.ai 模块单元测试

测试范围：
  - chat_completion() 的正常调用与返回值解析
  - API 返回异常结构时的错误处理
  - Authorization header 的正确组装
  - 请求 payload 的结构验证
"""
import pytest
import requests
from unittest.mock import patch, MagicMock

from insightbot.ai import chat_completion


# ── 辅助：构造标准 OpenAI 格式的 mock 响应 ────────────────────────────────────
def _make_mock_response(content: str, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [
            {"message": {"content": content, "role": "assistant"}}
        ]
    }
    return mock_resp


# ── 正常路径测试 ───────────────────────────────────────────────────────────────
class TestChatCompletionNormalPath:

    def test_returns_stripped_content(self):
        """应正确返回 AI 响应内容，并去除首尾空白。"""
        mock_resp = _make_mock_response("  这是一段营销分析内容。  ")
        with patch("insightbot.ai.requests.post", return_value=mock_resp) as mock_post:
            result = chat_completion(
                api_url="https://api.test.com/v1/chat/completions",
                api_key="test-key",
                model="test-model",
                system_prompt="你是营销分析师",
                user_text="分析这条新闻",
            )
        assert result == "这是一段营销分析内容。"
        mock_post.assert_called_once()

    def test_request_payload_structure(self):
        """请求 payload 必须包含 model、messages 和 temperature 字段。"""
        mock_resp = _make_mock_response("分析结果")
        with patch("insightbot.ai.requests.post", return_value=mock_resp) as mock_post:
            chat_completion(
                api_url="https://api.test.com/v1/chat/completions",
                api_key="test-key",
                model="deepseek-chat",
                system_prompt="系统提示词",
                user_text="用户输入",
                temperature=0.3,
            )
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["model"] == "deepseek-chat"
        assert payload["temperature"] == 0.3
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "系统提示词"
        assert payload["messages"][1]["role"] == "user"
        assert payload["messages"][1]["content"] == "用户输入"

    def test_authorization_header(self):
        """Authorization header 必须使用 Bearer 格式携带 API Key。"""
        mock_resp = _make_mock_response("ok")
        with patch("insightbot.ai.requests.post", return_value=mock_resp) as mock_post:
            chat_completion(
                api_url="https://api.test.com/v1/chat/completions",
                api_key="sk-secret-key-abc",
                model="test-model",
                system_prompt="sys",
                user_text="user",
            )
        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-secret-key-abc"
        assert headers["Content-Type"] == "application/json"

    def test_timeout_parameter_passed(self):
        """timeout_s 参数必须被正确传递给 requests.post。"""
        mock_resp = _make_mock_response("ok")
        with patch("insightbot.ai.requests.post", return_value=mock_resp) as mock_post:
            chat_completion(
                api_url="https://api.test.com/v1/chat/completions",
                api_key="key",
                model="model",
                system_prompt="sys",
                user_text="user",
                timeout_s=60,
            )
        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == 60


# ── 异常路径测试 ───────────────────────────────────────────────────────────────
class TestChatCompletionErrorPath:

    def test_raises_on_network_error(self):
        """网络请求失败时应向上抛出异常（由调用方的 retry 逻辑处理）。"""
        with patch("insightbot.ai.requests.post", side_effect=requests.exceptions.Timeout):
            with pytest.raises(requests.exceptions.Timeout):
                chat_completion(
                    api_url="https://api.test.com/v1/chat/completions",
                    api_key="key",
                    model="model",
                    system_prompt="sys",
                    user_text="user",
                )

    def test_raises_on_malformed_response(self):
        """API 返回格式异常时应抛出 KeyError（由调用方的 retry 逻辑处理）。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "invalid_api_key"}
        with patch("insightbot.ai.requests.post", return_value=mock_resp):
            with pytest.raises(KeyError):
                chat_completion(
                    api_url="https://api.test.com/v1/chat/completions",
                    api_key="bad-key",
                    model="model",
                    system_prompt="sys",
                    user_text="user",
                )

    def test_raises_runtime_error_on_http_error_payload(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"message": "model not found"}}
        with patch("insightbot.ai.requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="model not found"):
                chat_completion(
                    api_url="https://api.test.com/v1/chat/completions",
                    api_key="bad-key",
                    model="model",
                    system_prompt="sys",
                    user_text="user",
                )

    def test_non_json_error_includes_response_preview(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html><title>Bad Gateway</title></html>"
        mock_resp.json.side_effect = ValueError("not json")
        with patch("insightbot.ai.requests.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="text/html"):
                chat_completion(
                    api_url="https://api.test.com/v1/chat/completions",
                    api_key="key",
                    model="model",
                    system_prompt="sys",
                    user_text="user",
                )
