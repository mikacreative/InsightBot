"""
Channel-aware message rendering and delivery planning.

Pipelines still return a single final_markdown string. This module adapts that
string into channel-specific message batches before delivery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

CONTINUATION_HINT_TEMPLATE = "({index}/{total})"
WECOM_SOFT_LIMIT_BYTES = 3800
FEISHU_BOT_SOFT_LIMIT = 6000
FEISHU_APP_SOFT_LIMIT = 12000


@dataclass(frozen=True)
class ChannelMessage:
    content: str
    format: str = "markdown"
    title: str | None = None


@dataclass(frozen=True)
class DeliveryPlan:
    title: str
    messages: list[ChannelMessage]
    profile: dict[str, Any]


def build_delivery_plan(*, channel, content: str, config: dict, now: datetime | None = None) -> DeliveryPlan:
    settings = config.get("settings", {}) or {}
    report_date = (now or datetime.now()).strftime("%m-%d")
    title_template = settings.get("report_title", "📅 营销情报早报 | {date}")
    title = title_template.replace("{date}", report_date).strip()
    header = _build_header_markdown(title)
    footer = _build_footer_markdown(settings)
    profile = getattr(channel, "delivery_profile", {}) or {}
    channel_type = profile.get("channel_type", "generic")

    if not content:
        empty_message = settings.get("empty_message", "📭 今日全网无重要更新。").strip()
        return DeliveryPlan(
            title=title,
            messages=[ChannelMessage(content=empty_message, format=profile.get("preferred_format", "text"), title=title)],
            profile=profile,
        )

    if channel_type == "wecom":
        messages = _build_wecom_messages(title=title, header=header, content=content, footer=footer)
    elif channel_type == "feishu_app":
        messages = _build_feishu_app_messages(title=title, header=header, content=content, footer=footer)
    elif channel_type == "feishu_bot":
        messages = _build_text_messages(
            title=title,
            blocks=[header, content, footer],
            limit=FEISHU_BOT_SOFT_LIMIT,
            message_format="text",
            include_title=False,
        )
    else:
        messages = [ChannelMessage(content=_join_blocks([header, content, footer]), format="markdown", title=title)]

    return DeliveryPlan(title=title, messages=messages, profile=profile)


def _build_header_markdown(title: str) -> str:
    return f"# {title}\n> 正在为您通过 AI 融合检索定向信源与全网热词..."


def _build_footer_markdown(settings: dict) -> str:
    if not settings.get("show_footer", False):
        return ""
    return str(settings.get("footer_text", "")).strip()


def _join_blocks(blocks: list[str]) -> str:
    return "\n\n".join(block.strip() for block in blocks if str(block).strip()).strip()


def _build_wecom_messages(*, title: str, header: str, content: str, footer: str) -> list[ChannelMessage]:
    return _build_text_messages(
        title=title,
        blocks=[header, content, footer],
        limit=WECOM_SOFT_LIMIT_BYTES,
        message_format="markdown",
        include_title=False,
        byte_limit=True,
    )


def _build_feishu_app_messages(*, title: str, header: str, content: str, footer: str) -> list[ChannelMessage]:
    messages = _build_text_messages(
        title=title,
        blocks=[header, content, footer],
        limit=FEISHU_APP_SOFT_LIMIT,
        message_format="interactive",
        include_title=True,
    )
    if len(messages) <= 1:
        return messages

    total = len(messages)
    softened: list[ChannelMessage] = []
    for index, message in enumerate(messages, start=1):
        prefix = CONTINUATION_HINT_TEMPLATE.format(index=index, total=total) if index > 1 else ""
        softened.append(
            ChannelMessage(
                content=_join_blocks([prefix, message.content]),
                format="interactive",
                title=title,
            )
        )
    return softened


def _build_text_messages(
    *,
    title: str,
    blocks: list[str],
    limit: int,
    message_format: str,
    include_title: bool,
    byte_limit: bool = False,
) -> list[ChannelMessage]:
    reserved_limit = limit
    if byte_limit:
        reserved_limit = max(
            1,
            limit - _content_size(CONTINUATION_HINT_TEMPLATE.format(index=99, total=99) + "\n\n", byte_limit=True),
        )
    normalized_blocks: list[str] = []
    for block in blocks:
        normalized_blocks.extend(_normalize_blocks(block, reserved_limit, byte_limit=byte_limit))

    packed_messages = _pack_blocks(normalized_blocks, reserved_limit, byte_limit=byte_limit)
    if len(packed_messages) <= 1:
        return [
            ChannelMessage(
                content=packed_messages[0] if packed_messages else "",
                format=message_format,
                title=title if include_title else None,
            )
        ]

    total = len(packed_messages)
    result: list[ChannelMessage] = []
    for index, chunk in enumerate(packed_messages, start=1):
        prefix = CONTINUATION_HINT_TEMPLATE.format(index=index, total=total) if index > 1 else ""
        chunk_content = _join_blocks([prefix, chunk])
        result.append(
            ChannelMessage(
                content=chunk_content,
                format=message_format,
                title=title if include_title else None,
            )
        )
    return result


def _content_size(text: str, *, byte_limit: bool) -> int:
    if byte_limit:
        return len(str(text).encode("utf-8"))
    return len(str(text))


def _normalize_blocks(markdown: str, limit: int, *, byte_limit: bool = False) -> list[str]:
    markdown = str(markdown or "").strip()
    if not markdown:
        return []

    top_level_blocks = _split_preserving_sections(markdown)
    normalized: list[str] = []
    for block in top_level_blocks:
        if _content_size(block, byte_limit=byte_limit) <= limit:
            normalized.append(block)
            continue
        normalized.extend(_split_oversized_block(block, limit, byte_limit=byte_limit))
    return normalized


def _split_preserving_sections(markdown: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?m)(?=^##\s+)", markdown) if part.strip()]
    return parts or [markdown.strip()]


def _split_oversized_block(block: str, limit: int, *, byte_limit: bool = False) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", block) if paragraph.strip()]
    if not paragraphs:
        return _hard_split(block, limit, byte_limit=byte_limit)

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if _content_size(paragraph, byte_limit=byte_limit) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(paragraph, limit, byte_limit=byte_limit))
            continue

        candidate = _join_blocks([current, paragraph]) if current else paragraph
        if _content_size(candidate, byte_limit=byte_limit) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)
    return chunks


def _fit_prefix_by_size(text: str, limit: int, *, byte_limit: bool = False) -> str:
    if _content_size(text, byte_limit=byte_limit) <= limit:
        return text

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = text[:mid]
        if _content_size(candidate, byte_limit=byte_limit) <= limit:
            low = mid
        else:
            high = mid - 1
    return text[:low]


def _hard_split(text: str, limit: int, *, byte_limit: bool = False) -> list[str]:
    text = text.strip()
    if _content_size(text, byte_limit=byte_limit) <= limit:
        return [text]

    pieces: list[str] = []
    current = ""
    for line in text.splitlines():
        stripped = line.rstrip()
        candidate = f"{current}\n{stripped}".strip() if current else stripped
        if candidate and _content_size(candidate, byte_limit=byte_limit) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if _content_size(stripped, byte_limit=byte_limit) <= limit:
            current = stripped
            continue
        remainder = stripped
        while remainder:
            fitted = _fit_prefix_by_size(remainder, limit, byte_limit=byte_limit).strip()
            if not fitted:
                break
            pieces.append(fitted)
            remainder = remainder[len(fitted):].lstrip()
        current = ""
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def _pack_blocks(blocks: list[str], limit: int, *, byte_limit: bool = False) -> list[str]:
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = _join_blocks([current, block]) if current else block
        if not current or _content_size(candidate, byte_limit=byte_limit) <= limit:
            current = candidate
            continue
        chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    return chunks
