"""
Channel abstraction layer.

All pipeline code calls send_to_channel() rather than send_markdown_to_app directly.
This allows multiple channel types to be added without changing pipeline code.
"""

import logging
import os
from typing import Protocol, runtime_checkable

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


class ChannelRegistry:
    """Registry that holds all configured channel instances."""

    def __init__(self, channels_data: dict):
        self._channels: dict[str, Channel] = {}
        for ch_id, ch_def in channels_data.get("channels", {}).items():
            ch_type = ch_def.get("type", "wecom")
            if ch_type == "wecom":
                self._channels[ch_id] = WeChatChannel(
                    channel_id=ch_id,
                    name=ch_def.get("name", ch_id),
                    cid=ch_def.get("cid", ""),
                    secret=ch_def.get("secret", ""),
                    agent_id=ch_def.get("agent_id", ""),
                )

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


def all_channel_ids() -> list[str]:
    """List all registered channel IDs."""
    if _registry is None:
        return []
    return [ch.channel_id for ch in _registry.list()]
