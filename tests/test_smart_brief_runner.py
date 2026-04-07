"""
test_smart_brief_runner.py — insightbot.smart_brief_runner 核心逻辑测试

测试范围：
  - RSS 抓取：时效性过滤（24h）、链接去重
  - JSON 解析与 AI 重试行为
  - run_task()：完整流程的集成测试（全程 Mock 外部依赖）
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from insightbot.smart_brief_runner import (
    _ai_process_category,
    _validate_and_repair,
    fetch_recent_candidates,
    run_prompt_debug,
    run_task,
)


def _make_entry(title: str, link: str, hours_ago: float = 1.0):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.get = lambda key, default="": title if key == "summary" else default
    pub_time = datetime.now() - timedelta(hours=hours_ago)
    entry.published_parsed = pub_time.timetuple()
    return entry


def _make_feed(entries: list) -> MagicMock:
    feed = MagicMock()
    feed.entries = entries
    return feed


class TestJsonRepair:

    def test_parses_valid_json_items(self):
        raw = json.dumps(
            {
                "items": [
                    {
                        "title": "标题",
                        "url": "https://example.com/1",
                        "summary": "摘要",
                    }
                ]
            },
            ensure_ascii=False,
        )
        items = _validate_and_repair(raw)
        assert items == [{"title": "标题", "url": "https://example.com/1", "summary": "摘要"}]

    def test_returns_empty_for_invalid_json(self):
        assert _validate_and_repair("not json") == []

    def test_filters_invalid_urls(self):
        raw = json.dumps(
            {"items": [{"title": "标题", "url": "javascript:alert(1)", "summary": "摘要"}]},
            ensure_ascii=False,
        )
        assert _validate_and_repair(raw) == []


class TestFetchRecentCandidates:

    def test_recent_entries_are_included(self, silent_logger):
        recent_entry = _make_entry("近期文章标题", "https://example.com/recent", hours_ago=2)
        mock_feed = _make_feed([recent_entry])

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            news_list = fetch_recent_candidates(
                feed_data={"rss": ["https://example.com/feed.xml"], "keywords": [], "prompt": ""},
                logger=silent_logger,
            )

        links = [item["link"] for item in news_list]
        assert "https://example.com/recent" in links

    def test_stale_entries_are_excluded(self, silent_logger):
        stale_entry = _make_entry("过期文章标题", "https://example.com/stale", hours_ago=30)
        mock_feed = _make_feed([stale_entry])

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            news_list = fetch_recent_candidates(
                feed_data={"rss": ["https://example.com/feed.xml"], "keywords": [], "prompt": ""},
                logger=silent_logger,
            )

        assert news_list == []

    def test_entry_without_published_parsed_is_included(self, silent_logger):
        entry_no_time = MagicMock()
        entry_no_time.title = "无时间戳的文章"
        entry_no_time.link = "https://example.com/no-time"
        del entry_no_time.published_parsed
        mock_feed = _make_feed([entry_no_time])

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            news_list = fetch_recent_candidates(
                feed_data={"rss": ["https://example.com/feed.xml"], "keywords": [], "prompt": ""},
                logger=silent_logger,
            )

        links = [item["link"] for item in news_list]
        assert "https://example.com/no-time" in links

    def test_duplicate_links_are_deduplicated(self, silent_logger):
        dup_url = "https://example.com/dup"
        entries = [
            _make_entry("文章标题（原文）", dup_url, hours_ago=1),
            _make_entry("文章标题（转载）", dup_url, hours_ago=1),
            _make_entry("另一篇不重复的文章", "https://example.com/unique", hours_ago=1),
        ]
        mock_feed = _make_feed(entries)

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            news_list = fetch_recent_candidates(
                feed_data={"rss": ["https://example.com/feed.xml"], "keywords": [], "prompt": ""},
                logger=silent_logger,
            )

        links = [item["link"] for item in news_list]
        assert len(links) == 2
        assert links.count(dup_url) == 1
        assert "https://example.com/unique" in links


class TestPromptDebug:

    def _base_config(self):
        return {
            "ai": {
                "api_url": "https://api.test.com/v1/chat/completions",
                "api_key": "test-key",
                "model": "test-model",
                "system_prompt": "这是配置里的系统提示词",
            }
        }

    def test_returns_empty_for_empty_news_list(self, silent_logger):
        result = run_prompt_debug(
            config=self._base_config(),
            category_name="测试板块",
            news_list=[],
            category_prompt="",
            logger=silent_logger,
        )
        assert result["status"] == "empty_candidates"

    def test_empty_json_items_returns_empty(self, silent_logger):
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        with patch("insightbot.smart_brief_runner.chat_completion", return_value='{"items": []}'):
            result = run_prompt_debug(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result["status"] == "empty"

    def test_valid_json_becomes_markdown_preview(self, silent_logger):
        news_list = [{"title": "营销新闻", "link": "https://example.com/1"}]
        raw = json.dumps(
            {"items": [{"title": "营销新闻标题", "url": "https://example.com/1", "summary": "这是摘要内容"}]},
            ensure_ascii=False,
        )
        with patch("insightbot.smart_brief_runner.chat_completion", return_value=raw):
            result = run_prompt_debug(
                config=self._base_config(),
                category_name="营销板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result["status"] == "success"
        assert "## 营销板块" in result["preview_markdown"]
        assert "### [营销新闻标题](https://example.com/1)" in result["preview_markdown"]

    def test_ai_process_category_returns_preview_for_valid_json(self, silent_logger):
        news_list = [{"title": "营销新闻", "link": "https://example.com/1"}]
        raw = json.dumps(
            {"items": [{"title": "营销新闻标题", "url": "https://example.com/1", "summary": "这是摘要内容"}]},
            ensure_ascii=False,
        )
        with patch("insightbot.smart_brief_runner.chat_completion", return_value=raw):
            result = _ai_process_category(
                config=self._base_config(),
                category_name="营销板块",
                news_list=news_list,
                category_prompt="",
                logger=silent_logger,
            )
        assert result is not None
        assert "营销新闻标题" in result

    def test_category_prompt_appended_and_json_mode_enabled(self, silent_logger):
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        category_prompt = "只保留与数字营销相关的内容。"
        captured_calls = []

        def capture_call(**kwargs):
            captured_calls.append(kwargs)
            return '{"items": []}'

        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=capture_call):
            run_prompt_debug(
                config=self._base_config(),
                category_name="测试板块",
                news_list=news_list,
                category_prompt=category_prompt,
                logger=silent_logger,
            )

        assert len(captured_calls) == 1
        assert "这是配置里的系统提示词" in captured_calls[0]["system_prompt"]
        assert category_prompt in captured_calls[0]["system_prompt"]
        assert captured_calls[0]["json_mode"] is True

    def test_retry_on_exception(self, silent_logger):
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=Exception("API Error")) as mock_chat:
            with patch("insightbot.smart_brief_runner.time.sleep"):
                result = run_prompt_debug(
                    config=self._base_config(),
                    category_name="测试板块",
                    news_list=news_list,
                    category_prompt="",
                    logger=silent_logger,
                )
        assert result["status"] == "error"
        assert mock_chat.call_count == 3

    def test_succeeds_on_third_attempt_with_valid_json(self, silent_logger):
        news_list = [{"title": "新闻", "link": "https://example.com/1"}]
        side_effects = [
            Exception("fail1"),
            Exception("fail2"),
            '{"items": [{"title": "成功标题", "url": "https://example.com/1", "summary": "成功摘要"}]}',
        ]
        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=side_effects):
            with patch("insightbot.smart_brief_runner.time.sleep"):
                result = run_prompt_debug(
                    config=self._base_config(),
                    category_name="测试板块",
                    news_list=news_list,
                    category_prompt="",
                    logger=silent_logger,
                )
        assert result["status"] == "success"
        assert len(result["selected_items"]) == 1

    def test_input_text_truncated_to_batch_size_scope(self, silent_logger):
        news_list = [
            {"title": f"新闻标题{'x' * 200} {i}", "link": f"https://example.com/{i}"}
            for i in range(100)
        ]
        captured = []

        def capture(**kwargs):
            captured.append(kwargs["user_text"])
            return '{"items": []}'

        with patch("insightbot.smart_brief_runner.chat_completion", side_effect=capture):
            with patch("insightbot.smart_brief_runner.time.sleep"):
                run_prompt_debug(
                    config=self._base_config(),
                    category_name="测试板块",
                    news_list=news_list,
                    category_prompt="",
                    logger=silent_logger,
                )

        assert len(captured) > 1
        assert all(text.startswith("【待筛选列表】：\n") for text in captured)


class TestRunTaskIntegration:

    def test_sends_header_message_first(self, test_config, silent_logger):
        mock_feed = _make_feed([])
        sent_messages = []

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            with patch(
                "insightbot.smart_brief_runner.send_markdown_to_app",
                side_effect=lambda **kw: sent_messages.append(kw["content"]) or True,
            ):
                run_task(config=test_config, logger=silent_logger)

        assert len(sent_messages) >= 1
        assert "[TEST]" in sent_messages[0] or "营销情报" in sent_messages[0]

    def test_sends_empty_message_when_no_updates(self, test_config, silent_logger):
        mock_feed = _make_feed([])
        sent_messages = []

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            with patch(
                "insightbot.smart_brief_runner.send_markdown_to_app",
                side_effect=lambda **kw: sent_messages.append(kw["content"]) or True,
            ):
                run_task(config=test_config, logger=silent_logger)

        empty_msg = test_config["settings"]["empty_message"]
        assert any(empty_msg in msg for msg in sent_messages)

    def test_sends_footer_when_has_updates(self, test_config, silent_logger):
        recent_entry = _make_entry("营销新闻", "https://example.com/news", hours_ago=1)
        mock_feed = _make_feed([recent_entry])
        sent_messages = []

        with patch("insightbot.smart_brief_runner._parse_feed_url", return_value=mock_feed):
            with patch(
                "insightbot.smart_brief_runner.send_markdown_to_app",
                side_effect=lambda **kw: sent_messages.append(kw["content"]) or True,
            ):
                with patch(
                    "insightbot.smart_brief_runner._ai_process_category",
                    return_value="### [营销新闻](https://example.com/news)\n摘要",
                ):
                    with patch("insightbot.smart_brief_runner.time.sleep"):
                        run_task(config=test_config, logger=silent_logger)

        footer_text = test_config["settings"]["footer_text"]
        assert any(footer_text in msg for msg in sent_messages)

    def test_rss_fetch_failure_does_not_crash(self, test_config, silent_logger):
        with patch("insightbot.smart_brief_runner._parse_feed_url", side_effect=Exception("Connection refused")):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                run_task(config=test_config, logger=silent_logger)

    def test_url_comment_stripped(self, test_config, silent_logger):
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

        with patch("insightbot.smart_brief_runner._parse_feed_url", side_effect=capture_parse):
            with patch("insightbot.smart_brief_runner.send_markdown_to_app", return_value=True):
                run_task(config=config_with_comment, logger=silent_logger)

        assert len(parsed_urls) == 1
        assert "#" not in parsed_urls[0]
        assert parsed_urls[0].strip() == "https://example.com/feed.xml"
