"""
test_channels.py — insightbot.channels 核心逻辑测试

测试范围：
  - WeChatChannel.send() 和 test()
  - ChannelRegistry.get / list / add / remove
  - send_to_channel() 全局调用
  - test_channel() 联通性测试
  - init_channels() 初始化
"""

import pytest
from unittest.mock import MagicMock, patch


class TestWeChatChannel:
    def test_send_delegates_to_wecom(self):
        from insightbot.channels import WeChatChannel
        ch = WeChatChannel(
            channel_id="wecom_test",
            name="Test",
            cid="cid123",
            secret="secret456",
            agent_id="789",
        )
        with patch("insightbot.channels.send_markdown_to_app") as mock_send:
            mock_send.return_value = True
            result = ch.send("hello world")
            assert result is True
            mock_send.assert_called_once_with(
                cid="cid123",
                secret="secret456",
                agent_id="789",
                content="hello world",
            )

    def test_send_returns_false_on_failure(self):
        from insightbot.channels import WeChatChannel
        ch = WeChatChannel("wecom_test", "Test", cid="x", secret="y", agent_id="z")
        with patch("insightbot.channels.send_markdown_to_app") as mock_send:
            mock_send.return_value = False
            assert ch.send("content") is False

    def test_send_dry_run_mode(self):
        from insightbot.channels import WeChatChannel
        ch = WeChatChannel("wecom_test", "Test", cid="x", secret="y", agent_id="z")
        with patch.dict("os.environ", {"INSIGHTBOT_DRY_RUN": "1"}):
            with patch("insightbot.channels.send_markdown_to_app") as mock_send:
                result = ch.send("hello dry")
                assert result is True
                mock_send.assert_not_called()

    def test_test_sends_test_message(self):
        from insightbot.channels import WeChatChannel
        ch = WeChatChannel("wecom_test", "Test", cid="x", secret="y", agent_id="z")
        with patch("insightbot.channels.send_markdown_to_app") as mock_send:
            mock_send.return_value = True
            result = ch.test()
            assert result is True
            call_content = mock_send.call_args.kwargs["content"]
            assert "连通性测试" in call_content


class TestFeishuBotChannel:
    def test_send_delegates_to_feishu(self):
        from insightbot.channels import FeishuBotChannel

        ch = FeishuBotChannel(
            channel_id="feishu_test",
            name="Feishu",
            webhook_url="https://open.feishu.cn/webhook/abc",
            mention_all=True,
        )
        with patch("insightbot.channels.send_text_to_bot") as mock_send:
            mock_send.return_value = True
            result = ch.send("hello world")

        assert result is True
        mock_send.assert_called_once_with(
            webhook_url="https://open.feishu.cn/webhook/abc",
            content="hello world",
            mention_all=True,
        )

    def test_test_sends_test_message(self):
        from insightbot.channels import FeishuBotChannel

        ch = FeishuBotChannel(
            channel_id="feishu_test",
            name="Feishu",
            webhook_url="https://open.feishu.cn/webhook/abc",
        )
        with patch("insightbot.channels.send_text_to_bot") as mock_send:
            mock_send.return_value = True
            result = ch.test()

        assert result is True
        assert "飞书机器人配置正确" in mock_send.call_args.kwargs["content"]


class TestFeishuAppChannel:
    def test_send_interactive_delegates_to_feishu_app(self):
        from insightbot.channels import FeishuAppChannel

        ch = FeishuAppChannel(
            channel_id="feishu_app",
            name="飞书应用",
            app_id="cli_xxx",
            app_secret="secret_xxx",
            receive_id="oc_xxx",
            receive_id_type="open_id",
            message_template="interactive",
        )
        with patch("insightbot.channels.send_interactive_message") as mock_send:
            mock_send.return_value = True
            result = ch.send("## 报告")

        assert result is True
        mock_send.assert_called_once_with(
            app_id="cli_xxx",
            app_secret="secret_xxx",
            receive_id="oc_xxx",
            receive_id_type="open_id",
            title="飞书应用",
            markdown="## 报告",
        )

    def test_send_text_delegates_to_feishu_app(self):
        from insightbot.channels import FeishuAppChannel

        ch = FeishuAppChannel(
            channel_id="feishu_app",
            name="飞书应用",
            app_id="cli_xxx",
            app_secret="secret_xxx",
            receive_id="oc_xxx",
            message_template="text",
        )
        with patch("insightbot.channels.send_text_message") as mock_send:
            mock_send.return_value = True
            result = ch.send("hello")

        assert result is True
        mock_send.assert_called_once()


class TestChannelRegistry:
    def test_get_returns_channel(self):
        from insightbot.channels import ChannelRegistry, WeChatChannel
        registry = ChannelRegistry({
            "channels": {
                "ch1": {"type": "wecom", "name": "C1", "cid": "a", "secret": "b", "agent_id": "c"}
            }
        })
        ch = registry.get("ch1")
        assert ch is not None
        assert ch.channel_id == "ch1"

    def test_get_returns_none_for_missing(self):
        from insightbot.channels import ChannelRegistry
        registry = ChannelRegistry({"channels": {}})
        assert registry.get("nonexistent") is None

    def test_list_returns_all_channels(self):
        from insightbot.channels import ChannelRegistry
        registry = ChannelRegistry({
            "channels": {
                "ch1": {"type": "wecom", "name": "C1", "cid": "a", "secret": "b", "agent_id": "c"},
                "ch2": {"type": "wecom", "name": "C2", "cid": "d", "secret": "e", "agent_id": "f"},
            }
        })
        assert len(registry.list()) == 2

    def test_add_and_remove(self):
        from insightbot.channels import ChannelRegistry, WeChatChannel
        registry = ChannelRegistry({"channels": {}})
        ch = WeChatChannel("new_ch", "New", cid="a", secret="b", agent_id="c")
        registry.add(ch)
        assert registry.get("new_ch") is not None
        registry.remove("new_ch")
        assert registry.get("new_ch") is None

    def test_supports_feishu_bot(self):
        from insightbot.channels import ChannelRegistry, FeishuBotChannel

        registry = ChannelRegistry({
            "channels": {
                "feishu_main": {
                    "type": "feishu_bot",
                    "name": "飞书",
                    "webhook_url": "https://open.feishu.cn/webhook/abc",
                    "mention_all": True,
                }
            }
        })

        channel = registry.get("feishu_main")
        assert isinstance(channel, FeishuBotChannel)
        assert channel.mention_all is True

    def test_supports_feishu_app(self):
        from insightbot.channels import ChannelRegistry, FeishuAppChannel

        registry = ChannelRegistry({
            "channels": {
                "feishu_app": {
                    "type": "feishu_app",
                    "name": "飞书应用",
                    "app_id": "cli_xxx",
                    "app_secret": "secret",
                    "receive_id": "oc_xxx",
                    "receive_id_type": "open_id",
                    "message_template": "interactive",
                }
            }
        })

        channel = registry.get("feishu_app")
        assert isinstance(channel, FeishuAppChannel)
        assert channel.receive_id_type == "open_id"


class TestModuleLevelFunctions:
    def test_init_channels_sets_global_registry(self):
        from insightbot.channels import init_channels, _registry, all_channel_ids
        init_channels({
            "channels": {
                "ch1": {"type": "wecom", "name": "C1", "cid": "a", "secret": "b", "agent_id": "c"}
            }
        })
        assert all_channel_ids() == ["ch1"]

    def test_send_to_channel_raises_when_not_initialized(self):
        import insightbot.channels as ch_module
        ch_module._registry = None
        with pytest.raises(RuntimeError, match="not initialized"):
            ch_module.send_to_channel("ch1", "content")

    def test_get_channel_raises_key_error_when_missing(self):
        from insightbot.channels import init_channels, get_channel
        init_channels({"channels": {}})
        with pytest.raises(KeyError, match="not found"):
            get_channel("nonexistent")

    def test_all_channel_ids_empty_when_not_initialized(self):
        from insightbot.channels import all_channel_ids
        import insightbot.channels as ch_module
        ch_module._registry = None
        assert all_channel_ids() == []

    def test_test_channel_config_uses_unsaved_values(self):
        from insightbot.channels import test_channel_config

        with patch("insightbot.channels.send_text_to_bot") as mock_send:
            mock_send.return_value = True
            ok = test_channel_config(
                "feishu_preview",
                {
                    "type": "feishu_bot",
                    "name": "Preview",
                    "webhook_url": "https://open.feishu.cn/webhook/preview",
                    "mention_all": False,
                },
            )

        assert ok is True
        mock_send.assert_called_once()

    def test_validate_channel_definition_for_feishu_app(self):
        from insightbot.channels import validate_channel_definition

        result = validate_channel_definition(
            "feishu_app",
            {
                "type": "feishu_app",
                "name": "飞书应用",
                "app_id": "",
                "app_secret": "",
                "receive_id": "",
                "receive_id_type": "chat_id",
            },
        )

        assert result["is_ready"] is False
        codes = {issue["code"] for issue in result["issues"]}
        assert {"missing_app_id", "missing_app_secret", "missing_receive_id"} <= codes
