"""
test_smart_brief_runner.py — insightbot.smart_brief_runner 核心逻辑测试

测试范围：
  - RSS 抓取：时效性过滤（24h）、链接去重
  - _ai_process_category()：NONE 拦截、Prompt 组装、重试逻辑
  - run_task()：完整流程的集成测试（全程 Mock 外部依赖）
"""
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
import pytest

import feedparser

from insightbot.smart_brief_runner import _ai_process_category, run_task


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _make_entry(title: str, link: str, hours_ago: float = 1.0):
    """构造一个模拟的 feedparser entry 对象。"""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.get = lambda key, default="": title if key == "summary" else default
    pub_time = datetime.now() - timedelta(hours=hours_ago)
    entry.published_parsed = pub_time.timetuple()
    return entry


def _make_feed(entries: list) -> MagicMock:
    """构造一个模拟的 feedparser Feed 对象。"""
    feed = MagicMock()
    feed.entries = entries
    return feed


# ═══════════════════════════════════════════════════════════════════════════════
# 一、RSS 时效性过滤测试（通过 feedparser.parse 的 Mock 来测试 run_task 内部逻辑）
# ═══════════════════════════════════════════════════════════════════════════════
class TestRSSTimeFilter:

    def test_recent_entries_are_included(self, test_config, silent_logger):
        """发布时间在 24 小时内的文章应被纳入候选列表。"""
        recent_entry = _make_entry("近期文章标题", "https://example.com/recent", hours_ago=2)
        mock_feed = _make_feed([recent_entry])

        collected = []

        def fake_send(**kwargs):
            collected.append(kwargs.get("content", ""))
            return True

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", side_effect=fake_send):
                with patch("insightbot.smart_brief_runner._ai_process_category", return_value="### [近期文章](https://example.com/recent)\n摘要内容") as mock_ai:
                    run_task(config=test_config, logger=silent_logger)

        # 验证 AI 处理函数被调用，且传入了该文章
        assert mock_ai.called
        call_kwargs = mock_ai.call_args.kwargs
        news_list = call_kwargs["news_list"]
        links = [item["link"] for item in news_list]
        assert "https://example.com/recent" in links

    def test_stale_entries_are_excluded(self, test_config, silent_logger):
        """发布时间超过 24 小时的文章应被时效性过滤器拦截。"""
        stale_entry = _make_entry("过期文章标题", "https://example.com/stale", hours_ago=30)
        mock_feed = _make_feed([stale_entry])

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                with patch("insightbot.smart_brief_runner._ai_process_category") as mock_ai:
                    run_task(config=test_config, logger=silent_logger)

        # 过期文章不应触发 AI 处理
        mock_ai.assert_not_called()

    def test_entry_without_published_parsed_is_included(self, test_config, silent_logger):
        """没有 published_parsed 属性的文章（无时间信息）应被视为有效并纳入候选。"""
        entry_no_time = MagicMock()
        entry_no_time.title = "无时间戳的文章"
        entry_no_time.link = "https://example.com/no-time"
        # 模拟没有 published_parsed 属性
        del entry_no_time.published_parsed
        mock_feed = _make_feed([entry_no_time])

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                with patch("insightbot.smart_brief_runner._ai_process_category", return_value="摘要") as mock_ai:
                    run_task(config=test_config, logger=silent_logger)

        assert mock_ai.called
        call_kwargs = mock_ai.call_args.kwargs
        links = [item["link"] for item in call_kwargs["news_list"]]
        assert "https://example.com/no-time" in links


# ═══════════════════════════════════════════════════════════════════════════════
# 二、链接去重测试
# ═══════════════════════════════════════════════════════════════════════════════
class TestDeduplication:

    def test_duplicate_links_are_deduplicated(self, test_config, silent_logger):
        """相同链接的文章只应保留第一条，后续重复项应被去重。"""
        dup_url = "https://example.com/dup"
        entries = [
            _make_entry("文章标题（原文）", dup_url, hours_ago=1),
            _make_entry("文章标题（转载）", dup_url, hours_ago=1),
            _make_entry("另一篇不重复的文章", "https://example.com/unique", hours_ago=1),
        ]
        mock_feed = _make_feed(entries)

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                with patch("insightbot.smart_brief_runner._ai_process_category", return_value="摘要") as mock_ai:
                    run_task(config=test_config, logger=silent_logger)

        assert mock_ai.called
        call_kwargs = mock_ai.call_args.kwargs
        news_list = call_kwargs["news_list"]
        links = [item["link"] for item in news_list]
        # 去重后应只有 2 条（dup_url 只出现一次 + unique）
        assert len(links) == 2
        assert links.count(dup_url) == 1
        assert "https://example.com/unique" in links


# ═══════════════════════════════════════════════════════════════════════════════
# 三、AI 处理逻辑测试（_ai_process_category）
# ═══════════════════════════════════════════════════════════════════════════════
class TestAiProcessCategory:

    def _base_config(self):
        return {
            "ai": {
                "api_url": "https://api.test.com/v1/chat/completions",
                "api_key": "test-key",
                "model": "test-model",
                "system_prompt": "你是营销分析师。",
            }
        }

    def test_returns_none_for_empty_news_list(self, silent_logger):
        """空新闻列表应直接返回 None，不调用 AI。"""
        result = _ai_process_category(
            config=self._base_config(),
            category_name="测试板块",
            news_list=[],
            category_prompt="",
            logger=silent_logger,
        )
        assert result is None

    def test_none_response_is_intercepted(self, silent_logger):
        """AI 回复 'NONE' 时应被拦截，函数返回 None。"""
        news_list = [{"title": "无关新闻", "link": "https://example.com/1"}]
        with patch("insightbot.smart_brief_runner.chat_completion", return_value="NONE"):
            result = _ai_process_category(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result is None

    def test_none_in_longer_response_is_intercepted(self, silent_logger):
        """AI 回复中包含 'NONE'（即使有其他内容）也应被拦截。"""
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        with patch("insightbot.smart_brief_runner.chat_completion", return_value="经过分析，NONE符合标准"):
            result = _ai_process_category(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result is None

    def test_valid_response_is_returned(self, silent_logger):
        """AI 返回有效摘要时应直接返回该字符串。"""
        news_list = [{"title": "营销新闻", "link": "https://example.com/1"}]
        expected = "### [营销新闻标题](https://example.com/1)\n这是摘要内容。"
        with patch("insightbot.smart_brief_runner.chat_completion", return_value=expected):
            result = _ai_process_category(
                config=self._base_config(),
                category_name="营销板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result == expected

    def test_category_prompt_appended_to_system_prompt(self, silent_logger):
        """板块专属 Prompt 应被追加到系统提示词中。"""
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        category_prompt = "只保留与数字营销相关的内容。"
        captured_calls = []

        def capture_call(**kwargs):
            captured_calls.append(kwargs)
            return "有效摘要"

        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=capture_call):
            _ai_process_category(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt=category_prompt,
                logger=silent_logger,
            )

        assert len(captured_calls) == 1
        system_prompt_used = captured_calls[0]["system_prompt"]
        assert category_prompt in system_prompt_used
        assert "系统最高强制指令" in system_prompt_used

    def test_retry_on_exception(self, silent_logger):
        """AI 调用失败时应重试最多 3 次，全部失败后返回 None。"""
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=Exception("API Error")) as mock_chat:
            with patch("insightbot.smart_brief_runner.time.sleep"):  # 跳过等待
                result = _ai_process_category(
                    config=self._base_config(),
                    category_name="测试板块",
                    news_list=news_list,
                    category_prompt="",
                    logger=silent_logger,
                )
        assert result is None
        assert mock_chat.call_count == 3

    def test_succeeds_on_second_retry(self, silent_logger):
        """前两次失败、第三次成功时应返回有效结果。"""
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        side_effects = [Exception("fail1"), Exception("fail2"), "成功的摘要"]
        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=side_effects):
            with patch("insightbot.smart_brief_runner.time.sleep"):
                result = _ai_process_category(
                    config=self._base_config(),
                    category_name="测试板块",
                    news_list=news_list,
                    category_prompt="",
                    logger=silent_logger,
                )
        assert result == "成功的摘要"

    def test_input_text_truncated_to_15000_chars(self, silent_logger):
        """传给 AI 的 user_text 应被截断至 15000 字符以内。"""
        # 构造超长新闻列表
        news_list = [
            {"title": f"新闻标题{'x' * 200} {i}", "link": f"https://example.com/{i}"}
            for i in range(100)
        ]
        captured = []

        def capture(**kwargs):
            captured.append(kwargs["user_text"])
            return "摘要"

        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=capture):
            _ai_process_category(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )

        assert len(captured[0]) <= 15000


# ═══════════════════════════════════════════════════════════════════════════════
# 四、run_task 集成测试
# ═══════════════════════════════════════════════════════════════════════════════
class TestRunTaskIntegration:

    def test_sends_header_message_first(self, test_config, silent_logger):
        """任务开始时应首先推送包含标题的 header 消息。"""
        mock_feed = _make_feed([])
        sent_messages = []

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app",
                       side_effect=lambda **kw: sent_messages.append(kw["content"]) or True):
                run_task(config=test_config, logger=silent_logger)

        assert len(sent_messages) >= 1
        # 第一条消息应包含标题模板中的关键字
        assert "[TEST]" in sent_messages[0] or "营销情报" in sent_messages[0]

    def test_sends_empty_message_when_no_updates(self, test_config, silent_logger):
        """所有板块均无更新时应推送 empty_message。"""
        mock_feed = _make_feed([])
        sent_messages = []

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app",
                       side_effect=lambda **kw: sent_messages.append(kw["content"]) or True):
                run_task(config=test_config, logger=silent_logger)

        empty_msg = test_config["settings"]["empty_message"]
        assert any(empty_msg in msg for msg in sent_messages)

    def test_sends_footer_when_has_updates(self, test_config, silent_logger):
        """有内容更新时，若 show_footer=True，应推送 footer 消息。"""
        recent_entry = _make_entry("营销新闻", "https://example.com/news", hours_ago=1)
        mock_feed = _make_feed([recent_entry])
        sent_messages = []

        with patch("insightbot.smart_brief_runner.feedparser.parse", return_value=mock_feed):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app",
                       side_effect=lambda **kw: sent_messages.append(kw["content"]) or True):
                with patch("insightbot.smart_brief_runner._ai_process_category",
                           return_value="### [营销新闻](https://example.com/news)\n摘要"):
                    with patch("insightbot.smart_brief_runner.time.sleep"):
                        run_task(config=test_config, logger=silent_logger)

        footer_text = test_config["settings"]["footer_text"]
        assert any(footer_text in msg for msg in sent_messages)

    def test_rss_fetch_failure_does_not_crash(self, test_config, silent_logger):
        """RSS 抓取失败时任务应继续运行，不崩溃。"""
        with patch("insightbot.smart_brief_runner.feedparser.parse",
                   side_effect=Exception("Connection refused")):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                # 不应抛出异常
                run_task(config=test_config, logger=silent_logger)

    def test_url_comment_stripped(self, test_config, silent_logger):
        """RSS URL 中 # 后的注释部分应被自动剥离。"""
        config_with_comment = dict(test_config)
        config_with_comment["feeds"] = {
            "测试板块": {
                "rss": ["https://example.com/feed.xml  # 这是注释"],
                "keywords": [],
                "prompt": "",
            }
        }
        parsed_urls = []

        def capture_parse(url):
            parsed_urls.append(url)
            return _make_feed([])

        with patch("insightbot.smart_brief_runner.feedparser.parse", side_effect=capture_parse):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                run_task(config=config_with_comment, logger=silent_logger)

        assert len(parsed_urls) == 1
        assert "#" not in parsed_urls[0]
        assert parsed_urls[0].strip() == "https://example.com/feed.xml"
