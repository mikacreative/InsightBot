"""
conftest.py — Pytest 共享 Fixtures
所有测试模块均可直接使用这里定义的 fixture，无需额外 import。
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ── 项目根目录 & fixtures 目录 ──────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── 基础配置 fixture ──────────────────────────────────────────────────────────
@pytest.fixture
def test_config() -> dict:
    """加载标准测试配置字典（不依赖真实凭证）。"""
    config_path = FIXTURES_DIR / "config" / "test_config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 静默 logger fixture ───────────────────────────────────────────────────────
@pytest.fixture
def silent_logger() -> logging.Logger:
    """返回一个只写入内存、不输出到控制台的 logger，避免测试输出噪音。"""
    logger = logging.getLogger("insightbot.test")
    logger.setLevel(logging.DEBUG)
    # 清除已有 handler，防止多次测试叠加
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


# ── RSS fixture 路径辅助 ──────────────────────────────────────────────────────
@pytest.fixture
def rss_fixtures_dir() -> Path:
    """返回 RSS fixture 文件所在目录的 Path 对象。"""
    return FIXTURES_DIR / "rss"


@pytest.fixture
def recent_rss_path(rss_fixtures_dir: Path, tmp_path: Path) -> str:
    """
    返回「近期文章」RSS fixture 的本地文件路径（file:// URL 格式）。
    在返回前，将 TODAY_PLACEHOLDER 替换为真实的当前时间，确保时效性过滤测试准确。
    """
    src = rss_fixtures_dir / "marketing_recent.xml"
    content = src.read_text(encoding="utf-8")
    now_rfc822 = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    content = content.replace("TODAY_PLACEHOLDER", now_rfc822)
    dest = tmp_path / "marketing_recent.xml"
    dest.write_text(content, encoding="utf-8")
    return f"file://{dest}"


@pytest.fixture
def stale_rss_path(rss_fixtures_dir: Path) -> str:
    """返回「过期文章」RSS fixture 的本地文件路径（file:// URL 格式）。"""
    return f"file://{rss_fixtures_dir / 'marketing_stale.xml'}"


@pytest.fixture
def duplicate_rss_path(rss_fixtures_dir: Path, tmp_path: Path) -> str:
    """返回「含重复链接」RSS fixture 的本地文件路径，并替换时间占位符。"""
    src = rss_fixtures_dir / "marketing_duplicates.xml"
    content = src.read_text(encoding="utf-8")
    now_rfc822 = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    content = content.replace("TODAY_PLACEHOLDER", now_rfc822)
    dest = tmp_path / "marketing_duplicates.xml"
    dest.write_text(content, encoding="utf-8")
    return f"file://{dest}"
