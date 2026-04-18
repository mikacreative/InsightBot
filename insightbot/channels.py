"""
Channel abstraction layer.

All pipeline code calls send_to_channel() rather than send_markdown_to_app directly.
This allows multiple channel types to be added without changing pipeline code.
"""

import logging
import os
from typing import Protocol, runtime_checkable

from .feishu_app import send_interactive_message, send_text_message
from .feishu import send_text_to_bot
from .wecom import send_markdown_to_app

logger = logging.getLogger("Channels")


@runtime_checkable
class Channel(Protocol):
    """Protocol that all channel types must implement."""

    def send(self, content: str) -> bool:
        """Send content to the channel. Returns True on success."""
        ...

    def test(self) -> bool:
        """Send a connectivity test message. Returns True on success."""
        ...

    @property
    def channel_id(self) -> str:
        """Unique identifier for this channel."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name."""
        ...


class WeChatChannel:
    """WeChat Work (WeCom) channel implementation."""

    def __init__(
        self,
        channel_id: str,
        name: str,
        cid: str,
        secret: str,
        agent_id: str,
    ):
        self.channel_id = channel_id
        self.name = name
        self.cid = cid
        self.secret = secret
        self.agent_id = agent_id

    def send(self, content: str) -> bool:
        if os.getenv("INSIGHTBOT_DRY_RUN"):
            logger.info(f"[DRY_RUN] Would send to {self.channel_id}: {content[:50]}...")
            return True
        return send_markdown_to_app(
            cid=self.cid,
            secret=self.secret,
            agent_id=self.agent_id,
            content=content,
        )

    def test(self) -> bool:
        return send_markdown_to_app(
            cid=self.cid,
            secret=self.secret,
            agent_id=self.agent_id,
            content="✅ 频道连通性测试 — 此消息证明渠道配置正确。",
        )


class FeishuBotChannel:
    """Feishu incoming webhook bot implementation."""

    def __init__(
        self,
        channel_id: str,
        name: str,
        webhook_url: str,
        mention_all: bool = False,
    ):
        self.channel_id = channel_id
        self.name = name
        self.webhook_url = webhook_url
        self.mention_all = mention_all

    def send(self, content: str) -> bool:
        if os.getenv("INSIGHTBOT_DRY_RUN"):
            logger.info(f"[DRY_RUN] Would send to {self.channel_id}: {content[:50]}...")
            return True
        return send_text_to_bot(
            webhook_url=self.webhook_url,
            content=content,
            mention_all=self.mention_all,
        )

    def test(self) -> bool:
        return send_text_to_bot(
            webhook_url=self.webhook_url,
            content="✅ 频道连通性测试 - 此消息证明飞书机器人配置正确。",
            mention_all=self.mention_all,
        )


class FeishuAppChannel:
    """Feishu app channel with richer message support via official OpenAPI."""

    def __init__(
        self,
        channel_id: str,
        name: str,
        app_id: str,
        app_secret: str,
        receive_id: str,
        receive_id_type: str = "chat_id",
        message_template: str = "interactive",
    ):
        self.channel_id = channel_id
        self.name = name
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self.message_template = message_template

    def send(self, content: str) -> bool:
        if os.getenv("INSIGHTBOT_DRY_RUN"):
            logger.info(f"[DRY_RUN] Would send to {self.channel_id}: {content[:50]}...")
            return True

        if self.message_template == "text":
            return send_text_message(
                app_id=self.app_id,
                app_secret=self.app_secret,
                receive_id=self.receive_id,
                receive_id_type=self.receive_id_type,
                content=content,
            )

        return send_interactive_message(
            app_id=self.app_id,
            app_secret=self.app_secret,
            receive_id=self.receive_id,
            receive_id_type=self.receive_id_type,
            title=self.name,
            markdown=content,
        )

    def test(self) -> bool:
        return send_text_message(
            app_id=self.app_id,
            app_secret=self.app_secret,
            receive_id=self.receive_id,
            receive_id_type=self.receive_id_type,
            content="✅ 频道连通性测试 - 此消息证明飞书应用配置正确。",
        )


def validate_channel_definition(channel_id: str, channel_def: dict) -> dict:
    channel_type = channel_def.get("type", "wecom")
    issues = []

    def issue(code: str, message: str, field_path: str) -> None:
        issues.append({"code": code, "message": message, "field_path": field_path})

    if not str(channel_def.get("name", "")).strip():
        issue("missing_name", "频道名称不能为空。", "name")

    if channel_type == "wecom":
        if not str(channel_def.get("cid", "")).strip():
            issue("missing_cid", "企业微信 Corp ID 未填写。", "cid")
        if not str(channel_def.get("secret", "")).strip():
            issue("missing_secret", "企业微信 Secret 未填写。", "secret")
        if not str(channel_def.get("agent_id", "")).strip():
            issue("missing_agent_id", "企业微信 Agent ID 未填写。", "agent_id")
    elif channel_type == "feishu_app":
        if not str(channel_def.get("app_id", "")).strip():
            issue("missing_app_id", "飞书 App ID 未填写。", "app_id")
        if not str(channel_def.get("app_secret", "")).strip():
            issue("missing_app_secret", "飞书 App Secret 未填写。", "app_secret")
        if not str(channel_def.get("receive_id", "")).strip():
            issue("missing_receive_id", "飞书接收对象 ID 未填写。", "receive_id")
        if str(channel_def.get("receive_id_type", "")).strip() not in {"chat_id", "open_id", "user_id", "union_id", "email"}:
            issue("invalid_receive_id_type", "飞书接收对象类型无效。", "receive_id_type")
    elif channel_type == "feishu_bot":
        if not str(channel_def.get("webhook_url", "")).strip():
            issue("missing_webhook_url", "飞书机器人 Webhook URL 未填写。", "webhook_url")
    else:
        issue("unsupported_channel_type", f"不支持的频道类型：{channel_type}", "type")

    return {
        "channel_id": channel_id,
        "type": channel_type,
        "is_ready": not issues,
        "issues": issues,
    }


def build_channel(channel_id: str, ch_def: dict) -> Channel:
    ch_type = ch_def.get("type", "wecom")
    if ch_type == "wecom":
        return WeChatChannel(
            channel_id=channel_id,
            name=ch_def.get("name", channel_id),
            cid=ch_def.get("cid", ""),
            secret=ch_def.get("secret", ""),
            agent_id=ch_def.get("agent_id", ""),
        )
    if ch_type == "feishu_bot":
        return FeishuBotChannel(
            channel_id=channel_id,
            name=ch_def.get("name", channel_id),
            webhook_url=ch_def.get("webhook_url", ""),
            mention_all=bool(ch_def.get("mention_all", False)),
        )
    if ch_type == "feishu_app":
        return FeishuAppChannel(
            channel_id=channel_id,
            name=ch_def.get("name", channel_id),
            app_id=ch_def.get("app_id", ""),
            app_secret=ch_def.get("app_secret", ""),
            receive_id=ch_def.get("receive_id", ""),
            receive_id_type=ch_def.get("receive_id_type", "chat_id"),
            message_template=ch_def.get("message_template", "interactive"),
        )
    raise ValueError(f"Unsupported channel type: {ch_type}")


class ChannelRegistry:
    """Registry that holds all configured channel instances."""

    def __init__(self, channels_data: dict):
        self._channels: dict[str, Channel] = {}
        for ch_id, ch_def in channels_data.get("channels", {}).items():
            try:
                self._channels[ch_id] = build_channel(ch_id, ch_def)
            except ValueError as exc:
                logger.warning(f"Skipping channel '{ch_id}': {exc}")

    def get(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def list(self) -> list[Channel]:
        return list(self._channels.values())

    def add(self, channel: Channel) -> None:
        self._channels[channel.channel_id] = channel

    def remove(self, channel_id: str) -> None:
        self._channels.pop(channel_id, None)


# Global registry instance
_registry: ChannelRegistry | None = None


def init_channels(channels_data: dict) -> None:
    """Initialize the global channel registry. Call once at startup."""
    global _registry
    _registry = ChannelRegistry(channels_data)
    logger.info(f"Channel registry initialized with {len(_registry.list())} channels")


def get_channel(channel_id: str) -> Channel:
    """Get a channel by ID. Raises KeyError if not found."""
    if _registry is None:
        raise RuntimeError("ChannelRegistry not initialized. Call init_channels() first.")
    ch = _registry.get(channel_id)
    if ch is None:
        raise KeyError(f"Channel '{channel_id}' not found in registry.")
    return ch


def send_to_channel(channel_id: str, content: str) -> bool:
    """Unified send interface. All pipeline code uses this, not send_markdown_to_app directly."""
    return get_channel(channel_id).send(content)


def test_channel(channel_id: str) -> bool:
    """Send a connectivity test to the channel. Returns True/False."""
    return get_channel(channel_id).test()


def test_channel_config(channel_id: str, channel_def: dict) -> bool:
    """Send a connectivity test using the provided config, without saving it."""
    return build_channel(channel_id, channel_def).test()


def all_channel_ids() -> list[str]:
    """List all registered channel IDs."""
    if _registry is None:
        return []
    return [ch.channel_id for ch in _registry.list()]
