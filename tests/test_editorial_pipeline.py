"""
test_editorial_pipeline.py — insightbot.editorial_pipeline 核心逻辑测试

测试范围：
  - Stage 1: build_global_candidates — 全量源汇总、链接去重
  - Stage 2: screen_global_candidates — 3x倍率、全量 vs 分片模式
  - Stage 3: assign_candidates_to_categories — 单归属、空板块允许
  - Stage 4: select_for_category — AI 终筛并生成最终标题/摘要
  - run_editorial_pipeline — 完整流水线编排、灰度开关
"""
import json
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Mock feedparser and requests before importing editorial_pipeline
# (editorial_pipeline imports them at module level)
_mock_feedparser = MagicMock()
_mock_requests = MagicMock()
sys.modules['feedparser'] = _mock_feedparser
sys.modules['requests'] = _mock_requests

from insightbot.editorial_pipeline import (
    _assign_batch_once,
    _build_global_system_prompt,
    _build_publication_scope_summary,
    _call_global_screen_once,
    _normalize_global_items,
    _normalize_search_result,
    _parse_assignment_lines,
    _parse_assignment_response,
    _parse_final_edit_lines,
    _parse_global_screen_response,
    _parse_summary_lines,
    _remove_cross_category_duplicates,
    _validate_global_screen,
    assign_candidates_to_categories,
    build_global_candidates,
    run_editorial_pipeline,
    screen_global_candidates,
    select_for_category,
)


# ---------- Fixtures ----------

def _make_entry(title: str, link: str, hours_ago: float = 1.0, author: str = "Test Author"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = f"{title} 的摘要信息"
    entry.get = lambda key, default="": entry.summary if key == "summary" else default
    pub_time = datetime.now() - timedelta(hours=hours_ago)
    entry.published_parsed = pub_time.timetuple()
    entry.published = pub_time.isoformat()
    entry.author_detail = {"name": author}
    return entry


def _make_feed(entries: list) -> MagicMock:
    feed = MagicMock()
    feed.entries = entries
    return feed


def _editorial_config():
    return {
        "ai": {
            "system_prompt": "全局系统提示词",
            "api_url": "https://api.test.com/v1/chat/completions",
            "api_key": "test-key",
            "model": "test-model",
            "editorial_pipeline": {
                "enabled": True,
                "global_shortlist_multiplier": 3,
                "allow_multi_assign": False,
                "inject_publication_scope_into_global": True,
                "assignment_batch_size": 20,
                "selection": {
                    "max_selected_items": 10,
                    "title_max_len": 50,
                    "summary_max_len": 60,
                    "full_context_threshold_chars": 20000,
                    "batch_size": 20,
                },
            },
        },
        "sources": {
            "rss": [
                {
                    "id": "marketing_feed",
                    "url": "https://example-marketing.com/feed.xml",
                    "enabled": True,
                    "tags": ["marketing"],
                    "section_hints": ["💡 营销行业"],
                },
                {
                    "id": "ai_feed",
                    "url": "https://example-ai.com/feed.xml",
                    "enabled": True,
                    "tags": ["ai"],
                    "section_hints": ["🤖 数智前沿"],
                },
            ],
            "search": {"enabled": False, "queries": []},
        },
        "sections": {
            "💡 营销行业": {
                "keywords": [],
                "source_hints": ["marketing"],
                "prompt": "只保留与数字营销直接相关的内容。",
            },
            "🤖 数智前沿": {
                "keywords": ["AI营销", "智能广告"],
                "source_hints": ["ai"],
                "prompt": "只保留AI工具的实际应用案例。",
            },
        },
    }


# ---------- Stage 1: build_global_candidates ----------


class TestBuildGlobalCandidates:
    """测试全局候选池构建：RSS抓取 + 24h时效过滤 + 链接去重"""

    def test_aggregates_all_feed_sources(self, silent_logger):
        """所有板块的RSS源都应该被汇总到统一候选池"""
        entry1 = _make_entry("营销文章", "https://example.com/marketing-1", hours_ago=1)
        entry2 = _make_entry("AI工具文章", "https://example.com/ai-1", hours_ago=1)

        def mock_parse(url):
            if "marketing" in url:
                return _make_feed([entry1])
            return _make_feed([entry2])

        config = _editorial_config()
        with patch("insightbot.editorial_pipeline._parse_feed_url", side_effect=mock_parse):
            candidates = build_global_candidates(config=config, logger=silent_logger)

        links = [c["link"] for c in candidates]
        assert "https://example.com/marketing-1" in links
        assert "https://example.com/ai-1" in links
        assert len(candidates) == 2

    def test_recent_entries_are_included(self, silent_logger):
        """24小时以内的条目应该被包含"""
        entry = _make_entry("近期文章", "https://example.com/recent", hours_ago=2)
        with patch("insightbot.editorial_pipeline._parse_feed_url", return_value=_make_feed([entry])):
            candidates = build_global_candidates(
                config=_editorial_config(), logger=silent_logger
            )
        links = [c["link"] for c in candidates]
        assert "https://example.com/recent" in links

    def test_stale_entries_are_excluded(self, silent_logger):
        """超过24小时的条目应该被过滤"""
        entry = _make_entry("过期文章", "https://example.com/stale", hours_ago=30)
        with patch("insightbot.editorial_pipeline._parse_feed_url", return_value=_make_feed([entry])):
            candidates = build_global_candidates(
                config=_editorial_config(), logger=silent_logger
            )
        assert candidates == []

    def test_duplicate_links_are_deduplicated(self, silent_logger):
        """相同链接只保留一条"""
        entries = [
            _make_entry("原文标题", "https://example.com/dup", hours_ago=1),
            _make_entry("转载标题", "https://example.com/dup", hours_ago=1),
        ]
        with patch("insightbot.editorial_pipeline._parse_feed_url", return_value=_make_feed(entries)):
            candidates = build_global_candidates(
                config=_editorial_config(), logger=silent_logger
            )
        links = [c["link"] for c in candidates]
        assert links.count("https://example.com/dup") == 1
        assert len(links) == 1

    def test_returns_empty_list_when_all_feeds_fail(self, silent_logger):
        """所有RSS源都失败时返回空列表，不崩溃"""
        config = _editorial_config()
        with patch(
            "insightbot.editorial_pipeline._parse_feed_url",
            side_effect=Exception("Connection refused"),
        ):
            candidates = build_global_candidates(config=config, logger=silent_logger)
        assert candidates == []


class TestSearchCandidateNormalization:

    def test_drops_sogou_search_landing_pages(self):
        result = _normalize_search_result(
            {
                "title": "新智元 TTS 也要真人感",
                "link": "http://weixin.sogou.com/weixin?type=2&query=%E6%96%B0%E6%99%BA%E5%85%83",
                "snippet": "摘要",
                "source": "baidu",
            },
            section_hints=["🤖 数智前沿"],
        )
        assert result is None

    def test_normalizes_safe_search_result_urls(self):
        result = _normalize_search_result(
            {
                "title": "OpenAI 发布音频模型",
                "link": "https://example.com/a(b)?q=hello world",
                "snippet": "摘要",
                "source": "baidu",
            },
            section_hints=["🤖 数智前沿"],
        )
        assert result is not None
        assert result["link"] == "https://example.com/a%28b%29?q=hello+world"


# ---------- Stage 2: screen_global_candidates ----------


class TestScreenGlobalCandidates:
    """测试全局初筛：3x倍率、全量 vs 分片模式"""

    def test_returns_empty_when_candidates_empty(self, silent_logger):
        """空候选池直接返回空结果"""
        result = screen_global_candidates(config=_editorial_config(), candidates=[], logger=silent_logger)
        assert result["ok"] is True
        assert result["screened"] == []
        assert result["selection_mode"] == "empty"

    def test_shortlist_respects_3x_multiplier(self, silent_logger):
        """初筛结果数量应该接近 3x 目标数量"""
        candidates = [
            {"title": f"新闻{i}", "link": f"https://example.com/news{i}", "summary": "摘要"}
            for i in range(30)
        ]
        ai_response = json.dumps({
            "items": [
                {
                    "title": f"筛选{i}",
                    "link": f"https://example.com/selected{i}",
                    "summary": "摘要",
                    "priority_score": 0.8,
                    "editorial_note": "理由",
                }
                for i in range(10)
            ]
        }, ensure_ascii=False)

        with patch("insightbot.editorial_pipeline._call_global_screen_once", return_value={
            "ok": True,
            "record": {"status": "success"},
            "items": json.loads(ai_response)["items"],
            "error": None,
        }):
            result = screen_global_candidates(config=_editorial_config(), candidates=candidates, logger=silent_logger)

        assert result["ok"] is True
        assert len(result["screened"]) == 10
        assert result["selection_mode"] == "full"

    def test_uses_chunked_mode_when_over_threshold(self, silent_logger):
        """输入超过阈值时应该走分片模式"""
        # 制造大量候选，让输入文本超过阈值
        config = _editorial_config()
        config["ai"]["editorial_pipeline"]["selection"]["full_context_threshold_chars"] = 100
        config["ai"]["editorial_pipeline"]["selection"]["batch_size"] = 5

        candidates = [
            {
                "title": f"新闻{i}",
                "link": f"https://example.com/news{i}",
                "summary": "这是一段足够长的摘要，用来触发分片模式使输入超过阈值。",
            }
            for i in range(20)
        ]

        def mock_chunk_call(**kwargs):
            return {
                "ok": True,
                "record": {"stage": "global_chunk", "status": "success"},
                "items": [
                    {
                        "title": f"选中{i}",
                        "link": f"https://example.com/selected{i}",
                        "summary": "摘要",
                        "priority_score": 0.8,
                        "editorial_note": "理由",
                    }
                    for i in range(3)
                ],
                "error": None,
            }

        with patch("insightbot.editorial_pipeline._call_global_screen_once", side_effect=mock_chunk_call):
            with patch("insightbot.editorial_pipeline.time.sleep"):
                result = screen_global_candidates(config=config, candidates=candidates, logger=silent_logger)

        assert result["ok"] is True
        assert result["selection_mode"] == "chunked"

    def test_injects_publication_scope_when_enabled(self, silent_logger):
        """当 inject_publication_scope_into_global=True 时应该注入刊物定位"""
        config = _editorial_config()
        candidates = [{"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}]

        captured_prompts = []

        def mock_call(**kwargs):
            captured_prompts.append(kwargs["system_prompt"])
            return {
                "ok": True,
                "record": {"status": "success"},
                "items": [],
                "error": None,
            }

        with patch("insightbot.editorial_pipeline._call_global_screen_once", side_effect=mock_call):
            screen_global_candidates(config=config, candidates=candidates, logger=silent_logger)

        assert len(captured_prompts) == 1
        assert "💡 营销行业" in captured_prompts[0]
        assert "🤖 数智前沿" in captured_prompts[0]

    def test_screened_items_keep_source_category_hint_from_original_candidate(self, silent_logger):
        config = _editorial_config()
        candidates = [
            {
                "title": "品牌活人感",
                "link": "https://example.com/brand-human",
                "summary": "品牌社媒内容策略",
                "source_category_hint": "💡 营销行业",
                "source_name": "测试源",
            }
        ]

        with patch("insightbot.editorial_pipeline._call_global_screen_once", return_value={
            "ok": True,
            "record": {"status": "success"},
            "items": [
                {
                    "title": "品牌活人感",
                    "link": "https://example.com/brand-human",
                    "summary": "讲品牌如何提升社媒真实感。",
                    "priority_score": 0.86,
                    "editorial_note": "品牌内容策略参考",
                }
            ],
            "error": None,
        }):
            result = screen_global_candidates(config=config, candidates=candidates, logger=silent_logger)

        assert result["screened"][0]["source_category_hint"] == "💡 营销行业"
        assert result["screened"][0]["source_name"] == "测试源"

    def test_uses_conservative_fallback_when_global_ai_returns_empty_from_bad_response(self, silent_logger):
        config = _editorial_config()
        candidates = [
            {
                "title": "女性营销频频翻车，品牌没学会这3件事",
                "link": "https://example.com/marketing-risk",
                "summary": "盒马包装争议体现女性营销中的低俗暗示风险。",
                "source_category_hint": "💡 营销行业",
            },
            {
                "title": "Former Shaolin Temple Abbot Sentenced",
                "link": "https://example.com/shaolin",
                "summary": "A legal news item unrelated to marketing.",
                "source_category_hint": "📢 政策导向",
            },
        ]

        with patch("insightbot.editorial_pipeline._call_global_screen_once", return_value={
            "ok": True,
            "record": {"status": "empty", "raw_response": '{"items": [', "error": "timeout"},
            "items": [],
            "error": None,
        }):
            result = screen_global_candidates(config=config, candidates=candidates, logger=silent_logger)

        assert result["ok"] is True
        assert [item["link"] for item in result["screened"]] == ["https://example.com/marketing-risk"]
        assert result["screened"][0]["editorial_note"] == "模型初筛不可用，按来源与关键词兜底保留"


class TestBuildGlobalSystemPrompt:
    """测试全局初筛 prompt 构建"""

    def test_removes_legacy_markdown_output_instructions_from_base_prompt(self):
        base_prompt = """你是一个资深营销情报官。

【输出标准 - 必须严格遵守】
1. 格式：
### [重构后的标题](原文链接)
> 💡 *摘要内容*

不要输出任何开场白，直接列出内容。"""

        prompt = _build_global_system_prompt(
            base_prompt,
            selection_settings={
                "max_selected_items": 10,
                "title_max_len": 50,
                "summary_max_len": 60,
            },
            publication_scope="【营销行业】只保留中国大陆营销案例",
        )

        assert "### [重构后的标题]" not in prompt
        assert "> 💡 *摘要内容*" not in prompt
        assert "候选筛选器" in prompt
        assert "不要改写成 Markdown" in prompt
        assert "只输出 JSON" in prompt


class TestValidateGlobalScreen:
    """测试全局初筛 AI 返回解析"""

    def test_parses_valid_json_with_priority_score(self):
        raw = json.dumps({
            "items": [
                {
                    "title": "测试标题",
                    "link": "https://example.com/1",
                    "summary": "测试摘要",
                    "priority_score": 0.9,
                    "editorial_note": "很有价值",
                }
            ]
        }, ensure_ascii=False)
        settings = {
            "max_selected_items": 10,
            "title_max_len": 50,
            "summary_max_len": 60,
        }
        items = _validate_global_screen(raw, selection_settings=settings)
        assert len(items) == 1
        assert items[0]["priority_score"] == 0.9
        assert items[0]["editorial_note"] == "很有价值"

    def test_filters_empty_urls(self):
        """空URL应该被过滤"""
        raw = json.dumps({
            "items": [
                {"title": "标题", "link": "", "summary": "摘要"}
            ]
        }, ensure_ascii=False)
        items = _validate_global_screen(raw, selection_settings={
            "max_selected_items": 10, "title_max_len": 50, "summary_max_len": 60
        })
        assert items == []

    def test_returns_empty_for_invalid_json(self):
        items = _validate_global_screen("not json", selection_settings={
            "max_selected_items": 10, "title_max_len": 50, "summary_max_len": 60
        })
        assert items == []

    def test_extracts_json_from_surrounding_text(self):
        raw = '结果如下：{"items":[{"title":"标题","link":"https://example.com/1","summary":"摘要","priority_score":0.8}]}'
        items = _validate_global_screen(raw, selection_settings={
            "max_selected_items": 10, "title_max_len": 50, "summary_max_len": 60
        })
        assert len(items) == 1
        assert items[0]["link"] == "https://example.com/1"

    def test_retries_invalid_text_before_returning_items(self):
        valid = json.dumps({
            "items": [
                {
                    "title": "新闻",
                    "link": "https://example.com/1",
                    "summary": "摘要",
                    "priority_score": 0.8,
                    "editorial_note": "理由",
                }
            ]
        }, ensure_ascii=False)
        with patch("insightbot.editorial_pipeline.chat_completion", side_effect=["not json", valid]) as mock_ai:
            with patch("insightbot.editorial_pipeline.time.sleep"):
                result = _call_global_screen_once(
                    config=_editorial_config(),
                    news_list=[
                        {
                            "title": "新闻",
                            "link": "https://example.com/1",
                            "summary": "摘要",
                            "source_section_hints": ["💡 营销行业"],
                        }
                    ],
                    system_prompt="只输出 JSON",
                    selection_settings={
                        "max_selected_items": 10,
                        "title_max_len": 50,
                        "summary_max_len": 60,
                    },
                    stage_label="global_full",
                    batch_no=1,
                )
        assert mock_ai.call_count == 2
        assert result["items"][0]["link"] == "https://example.com/1"
        assert result["items"][0]["title"] == "新闻"
        assert result["items"][0]["priority_score"] == 0.8

    def test_global_screen_filters_low_score_rejected_items(self):
        candidates = [
            {"title": "保留", "link": "https://example.com/keep", "summary": "摘要"},
            {"title": "排除", "link": "https://example.com/drop", "summary": "摘要"},
        ]
        raw = json.dumps({
            "items": [
                {"title": "保留", "link": "https://example.com/keep", "summary": "摘要", "priority_score": 0.75, "editorial_note": "有价值"},
                {"title": "排除", "link": "https://example.com/drop", "summary": "摘要", "priority_score": 0.10, "editorial_note": "排除"},
            ]
        }, ensure_ascii=False)
        result = _parse_global_screen_response(
            raw,
            candidates,
            selection_settings={
                "max_selected_items": 10,
                "title_max_len": 50,
                "summary_max_len": 60,
                "min_priority_score": 0.5,
            },
        )

        assert [item["link"] for item in result] == ["https://example.com/keep"]


class TestCallGlobalScreenOnce:
    """测试全局初筛单次调用的重试语义"""

    def test_retries_when_response_is_malformed_json_then_uses_valid_result(self):
        malformed = '{\n  "items": [    {      "": "  "      ,      ,      "'
        valid = json.dumps({
            "items": [
                {
                    "title": "盒马粉木耳包装翻车",
                    "link": "https://example.com/hema",
                    "summary": "女性营销符号误用，品牌需避开低俗暗示。",
                    "priority_score": 0.82,
                    "editorial_note": "中国消费品牌传播风险案例",
                }
            ]
        }, ensure_ascii=False)

        with patch("insightbot.editorial_pipeline.chat_completion", side_effect=[malformed, valid]) as mock_chat:
            with patch("insightbot.editorial_pipeline.time.sleep"):
                result = _call_global_screen_once(
                    config=_editorial_config(),
                    news_list=[{"title": "盒马粉木耳包装翻车", "link": "https://example.com/hema", "summary": "摘要"}],
                    system_prompt="只输出 JSON",
                    selection_settings={
                        "max_selected_items": 10,
                        "title_max_len": 50,
                        "summary_max_len": 60,
                    },
                    stage_label="global_full",
                    batch_no=1,
                )

        assert mock_chat.call_count == 2
        assert result["ok"] is True
        assert result["items"][0]["link"] == "https://example.com/hema"
        assert result["record"]["status"] == "success"

    def test_does_not_retry_explicit_empty_items(self):
        raw = json.dumps({"items": []}, ensure_ascii=False)

        with patch("insightbot.editorial_pipeline.chat_completion", return_value=raw) as mock_chat:
            result = _call_global_screen_once(
                config=_editorial_config(),
                news_list=[{"title": "无关内容", "link": "https://example.com/off", "summary": "摘要"}],
                system_prompt="只输出 JSON",
                selection_settings={
                    "max_selected_items": 10,
                    "title_max_len": 50,
                    "summary_max_len": 60,
                },
                stage_label="global_full",
                batch_no=1,
            )

        assert mock_chat.call_count == 1
        assert result["ok"] is True
        assert result["items"] == []
        assert result["record"]["status"] == "empty"


class TestNormalizeGlobalItems:
    """测试全局初筛结果标准化"""

    def test_deduplicates_by_url(self):
        items = [
            {"title": "标题1", "link": "https://example.com/1", "summary": "摘要", "priority_score": 0.5},
            {"title": "标题2", "link": "https://example.com/1", "summary": "摘要2", "priority_score": 0.6},
        ]
        settings = {"title_max_len": 50, "summary_max_len": 60}
        result = _normalize_global_items(items, selection_settings=settings)
        assert len(result) == 1

    def test_preserves_priority_score_and_editorial_note(self):
        """优先级分数和编辑备注应该被保留"""
        items = [
            {
                "title": "标题",
                "link": "https://example.com/1",
                "summary": "摘要",
                "priority_score": 0.9,
                "editorial_note": "重要",
            }
        ]
        settings = {"title_max_len": 50, "summary_max_len": 60}
        result = _normalize_global_items(items, selection_settings=settings)
        assert len(result) == 1
        assert result[0]["priority_score"] == 0.9
        assert result[0]["editorial_note"] == "重要"


# ---------- Stage 3: assign_candidates_to_categories ----------


class TestAssignCandidatesToCategories:
    """测试板块分配：单归属、空板块允许"""

    def test_returns_empty_map_when_no_candidates(self, silent_logger):
        """无候选时返回空映射"""
        config = _editorial_config()
        result = assign_candidates_to_categories(
            config=config, screened_candidates=[], logger=silent_logger
        )
        assert result["ok"] is True
        assert result["category_candidate_map"] == {"💡 营销行业": [], "🤖 数智前沿": []}
        assert result["unassigned"] == []

    def test_single_assignment_per_candidate(self, silent_logger):
        """一条内容只应归属一个板块"""
        candidates = [
            {"title": "文章1", "link": "https://example.com/1", "summary": "摘要"},
        ]
        config = _editorial_config()

        # 直接 mock _assign_batch_once 返回值，验证单归属结构
        with patch("insightbot.editorial_pipeline._assign_batch_once", return_value={
            "assignments": {"💡 营销行业": candidates, "🤖 数智前沿": []},
            "unassigned": [],
            "record": {"status": "success"},
        }):
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        # 验证单归属：候选只出现在一个板块
        marketing_assigned = result["category_candidate_map"]["💡 营销行业"]
        ai_assigned = result["category_candidate_map"]["🤖 数智前沿"]
        assert len(marketing_assigned) == 1
        assert len(ai_assigned) == 0
        assert marketing_assigned[0]["link"] == "https://example.com/1"

    def test_unassigned_candidates_are_tracked(self, silent_logger):
        """无法分配到任何板块的候选应该被记录到 unassigned"""
        candidates = [
            {"title": "无关内容", "link": "https://example.com/irrelevant", "summary": "摘要"},
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline._assign_batch_once", return_value={
            "assignments": {"💡 营销行业": [], "🤖 数智前沿": []},
            "unassigned": candidates,
            "record": {"status": "success"},
        }):
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        assert len(result["unassigned"]) == 1
        assert result["unassigned"][0]["link"] == "https://example.com/irrelevant"

    def test_assign_batch_falls_back_to_source_category_hint_when_ai_returns_empty(self, silent_logger):
        config = _editorial_config()
        candidates = [
            {
                "title": "女性营销翻车案例",
                "link": "https://example.com/marketing",
                "summary": "中国品牌沟通风险案例。",
                "priority_score": 0.9,
                "source_category_hint": "💡 营销行业",
            },
            {
                "title": "AI 营销工具实战",
                "link": "https://example.com/ai",
                "summary": "AI 工具在内容生产中的应用。",
                "priority_score": 0.7,
                "source_category_hint": "🤖 数智前沿",
            },
        ]

        with patch("insightbot.editorial_pipeline._assign_batch_once", return_value={
            "assignments": {},
            "unassigned": candidates,
            "record": {"status": "empty"},
        }):
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        assert [item["link"] for item in result["category_candidate_map"]["💡 营销行业"]] == ["https://example.com/marketing"]
        assert [item["link"] for item in result["category_candidate_map"]["🤖 数智前沿"]] == ["https://example.com/ai"]
        assert result["unassigned"] == []


class TestBuildPublicationScopeSummary:
    """测试刊物整体栏目定位摘要构建"""

    def test_includes_all_category_prompts(self):
        config = _editorial_config()
        summary = _build_publication_scope_summary(config)
        assert "💡 营销行业" in summary
        assert "🤖 数智前沿" in summary
        assert "只保留与数字营销直接相关的内容" in summary
        assert "只保留AI工具的实际应用案例" in summary


# ---------- Stage 4: select_for_category ----------


class TestSelectForCategory:
    """测试板块最终输出：AI 终筛并生成最终标题/摘要，代码只校验与渲染"""

    def test_uses_ai_final_title_summary_and_code_owned_url(self, silent_logger):
        candidates = [
            {
                "title": "[RSS] 文章频道 - 原始长标题",
                "link": "https://example.com/1",
                "summary": "测试摘要",
                "priority_score": 0.8,
                "editorial_note": "理由",
                "image_url": "https://cdn.example.com/cover.jpg",
            }
        ]
        config = _editorial_config()
        fake_result = {
            "status": "success",
            "category": "💡 营销行业",
            "selected_items": [
                {"title": "AI改写标题", "url": "https://example.com/1", "summary": "AI改写摘要，说明营销启示"}
            ],
            "preview_markdown": "## 💡 营销行业\n\n### [AI改写标题](https://example.com/1)\n> 💡 AI改写摘要，说明营销启示",
            "batches": [],
            "selection_mode": "ai_final_edit",
        }

        with patch("insightbot.editorial_pipeline.run_prompt_debug", return_value=fake_result) as mock_run:
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        mock_run.assert_called_once()
        assert result["selection_mode"] == "ai_final_edit"
        assert result["status"] == "success"
        assert result["selected_items"] == [
            {
                "title": "AI改写标题",
                "url": "https://example.com/1",
                "summary": "AI改写摘要，说明营销启示",
                "image_url": "https://cdn.example.com/cover.jpg",
            }
        ]
        assert "### [AI改写标题](https://example.com/1)" in result["preview_markdown"]

    def test_does_not_backfill_when_ai_keeps_fewer_than_max(self, silent_logger):
        candidates = [
            {"title": f"候选{i}", "link": f"https://example.com/{i}", "summary": "摘要", "priority_score": 0.9 - i * 0.01}
            for i in range(1, 6)
        ]
        config = _editorial_config()
        fake_result = {
            "status": "success",
            "category": "💡 营销行业",
            "selected_items": [
                {"title": "保留一", "url": "https://example.com/1", "summary": "摘要一说明营销启示"},
                {"title": "保留二", "url": "https://example.com/2", "summary": "摘要二说明营销启示"},
            ],
            "preview_markdown": "## 💡 营销行业\n\n### [保留一](https://example.com/1)\n> 💡 摘要一\n\n### [保留二](https://example.com/2)\n> 💡 摘要二",
            "batches": [],
            "selection_mode": "ai_final_edit",
        }

        with patch("insightbot.editorial_pipeline.run_prompt_debug", return_value=fake_result):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["status"] == "success"
        assert [item["title"] for item in result["selected_items"]] == ["保留一", "保留二"]

    def test_invalid_ai_final_copy_is_dropped_without_code_fallback(self, silent_logger):
        candidates = [
            {
                "title": "Nike Reveals a World Cup Universe",
                "link": "https://example.com/nike",
                "summary": "Nike launches World Cup creative platform.",
                "priority_score": 0.9,
            },
        ]
        config = _editorial_config()
        fake_result = {
            "status": "success",
            "category": "💡 营销行业",
            "selected_items": [],
            "preview_markdown": "",
            "batches": [],
            "selection_mode": "ai_final_edit",
        }

        with patch("insightbot.editorial_pipeline.run_prompt_debug", return_value=fake_result):
            with patch("insightbot.editorial_pipeline.time.sleep"):
                result = select_for_category(
                    config=config,
                    category_name="💡 营销行业",
                    candidates=candidates,
                    logger=silent_logger,
                )

        assert result["status"] == "fallback"
        assert len(result["selected_items"]) >= 1

    def test_final_edit_parser_rejects_truncated_and_generic_fallback_copy(self):
        parsed = _parse_final_edit_lines(
            "C001 | KEEP | 标题... | 标题...，需关注其对品牌传播与消费沟通的影响 | bad\n"
            "C002 | KEEP | 完整标题 | 事件说明清楚，并给出具体营销启示 | ok\n"
            "C003 | DROP | - | - | low",
            {"C001", "C002", "C003"},
            title_max_len=30,
            summary_max_len=60,
        )
        assert "C001" not in parsed
        assert parsed["C002"]["status"] == "KEEP"
        assert parsed["C003"]["status"] == "DROP"

    def test_summary_parser_rejects_none_and_strips_markdown(self):
        parsed = _parse_summary_lines(
            "C001 | NONE\nC002 | 💡 *有效摘要内容*",
            {"C001", "C002"},
            summary_max_len=50,
        )
        assert parsed == {"C002": "有效摘要内容"}

    def test_cross_category_dedupe_helper_still_drops_repeated_topics(self):
        result = {
            "status": "success",
            "selected_items": [
                {"title": "小红书买下世界杯版权", "url": "https://example.com/1", "summary": "摘要"},
                {"title": "完全不同标题", "url": "https://example.com/2", "summary": "摘要"},
            ],
            "preview_markdown": "old",
        }
        filtered = _remove_cross_category_duplicates(
            result,
            seen_titles=["2026世界杯，为什么小红书买了"],
            category_name="🤖 数智前沿",
        )
        assert filtered["dedupe_dropped"] == 1
        assert [item["title"] for item in filtered["selected_items"]] == ["完全不同标题"]

    def test_returns_empty_when_no_candidates(self, silent_logger):
        config = _editorial_config()
        result = select_for_category(
            config=config,
            category_name="💡 营销行业",
            candidates=[],
            logger=silent_logger,
        )
        assert result["status"] == "empty_candidates"

    def test_falls_back_to_candidate_markdown_when_final_ai_returns_empty(self, silent_logger):
        config = _editorial_config()
        candidates = [
            {
                "title": "[RSS] 女性营销频频翻车，品牌没学会这3件事",
                "link": "https://example.com/marketing-risk",
                "summary": "盒马包装争议体现女性营销中的低俗暗示风险。",
                "priority_score": 0.82,
            }
        ]

        with patch("insightbot.smart_brief_runner.run_prompt_debug", return_value={
            "status": "empty",
            "selected_items": [],
            "preview_markdown": "",
        }):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["status"] == "fallback"
        assert result["selected_items"][0]["url"] == "https://example.com/marketing-risk"
        assert "女性营销频频翻车" in result["preview_markdown"]

    def test_falls_back_when_final_ai_output_has_empty_summary(self, silent_logger):
        config = _editorial_config()
        candidates = [
            {
                "title": "[RSS] AI的下一个战场是宠物机器人",
                "link": "https://example.com/ai-pet",
                "summary": "AI宠物机器人反映年轻人情感陪伴消费趋势。",
                "priority_score": 0.9,
            }
        ]

        with patch("insightbot.smart_brief_runner.run_prompt_debug", return_value={
            "status": "success",
            "selected_items": [{"title": "AI宠物机器人", "url": "https://example.com/ai-pet", "summary": ""}],
            "preview_markdown": "## 🤖 数智前沿\n### [AI宠物机器人](https://example.com/ai-pet)\n> 💡 **",
        }):
            result = select_for_category(
                config=config,
                category_name="🤖 数智前沿",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["status"] == "fallback"
        assert "AI宠物机器人反映年轻人情感陪伴消费趋势" in result["preview_markdown"]


# ---------- Orchestration: run_editorial_pipeline ----------


class TestRunEditorialPipeline:
    """测试完整流水线编排"""

    def test_returns_error_when_screening_fails(self, silent_logger):
        """全局初筛失败时整体返回错误"""
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.build_global_candidates", return_value=[
            {"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}
        ]):
            with patch("insightbot.editorial_pipeline.screen_global_candidates", return_value={
                "ok": False,
                "error": "API Error",
                "screened": [],
                "global_shortlist_size": 0,
                "selection_mode": "full",
                "batches": [],
                "system_prompt": "",
            }):
                result = run_editorial_pipeline(config=config, logger=silent_logger)

        assert result["ok"] is False
        assert result["error"] == "API Error"

    def test_runs_all_stages_when_enabled(self, silent_logger):
        """enabled=True 时应该执行所有阶段"""
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.build_global_candidates") as mock_build:
            with patch("insightbot.editorial_pipeline.screen_global_candidates") as mock_screen:
                with patch("insightbot.editorial_pipeline.assign_candidates_to_categories") as mock_assign:
                    with patch("insightbot.editorial_pipeline.select_for_category") as mock_select:
                        mock_build.return_value = [
                            {"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}
                        ]
                        mock_screen.return_value = {
                            "ok": True,
                            "screened": [
                                {"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}
                            ],
                            "global_shortlist_size": 1,
                            "selection_mode": "full",
                            "batches": [],
                            "system_prompt": "",
                            "error": None,
                        }
                        mock_assign.return_value = {
                            "ok": True,
                            "category_candidate_map": {"💡 营销行业": [], "🤖 数智前沿": []},
                            "unassigned": [],
                            "error": None,
                        }
                        mock_select.return_value = {"status": "empty_candidates", "selected_items": []}

                        result = run_editorial_pipeline(config=config, logger=silent_logger)

        mock_build.assert_called_once()
        mock_screen.assert_called_once()
        mock_assign.assert_called_once()
        assert result["ok"] is True

    def test_returns_full_debug_result(self, silent_logger):
        """应该返回完整的中间结果便于调试"""
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.build_global_candidates", return_value=[]):
            with patch("insightbot.editorial_pipeline.screen_global_candidates", return_value={
                "ok": True,
                "screened": [],
                "global_shortlist_size": 0,
                "selection_mode": "empty",
                "batches": [],
                "system_prompt": "",
                "error": None,
            }):
                result = run_editorial_pipeline(config=config, logger=silent_logger)

        assert "global_candidates" in result
        assert "screened_result" in result
        assert "assignment_result" in result
        assert "category_results" in result
        assert "final_markdown" in result

    def test_includes_fallback_category_markdown_in_final_output(self, silent_logger):
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.build_global_candidates", return_value=[
            {"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}
        ]):
            with patch("insightbot.editorial_pipeline.screen_global_candidates", return_value={
                "ok": True,
                "screened": [{"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}],
                "global_shortlist_size": 1,
                "selection_mode": "full",
                "batches": [],
                "system_prompt": "",
                "error": None,
            }):
                with patch("insightbot.editorial_pipeline.assign_candidates_to_categories", return_value={
                    "ok": True,
                    "category_candidate_map": {
                        "💡 营销行业": [{"title": "新闻", "link": "https://example.com/1", "summary": "摘要"}],
                        "🤖 数智前沿": [],
                    },
                    "unassigned": [],
                    "error": None,
                }):
                    with patch("insightbot.editorial_pipeline.select_for_category", return_value={
                        "status": "fallback",
                        "selected_items": [{"title": "新闻", "url": "https://example.com/1", "summary": "摘要"}],
                        "preview_markdown": "## 💡 营销行业\n### [新闻](https://example.com/1)",
                    }):
                        result = run_editorial_pipeline(config=config, logger=silent_logger)

        assert "## 💡 营销行业" in result["final_markdown"]


# ---------- Rollout: enabled flag ----------

class TestEditorialPipelineEnabledFlag:
    """测试灰度开关：enabled=false 时旧流程不受影响"""

    def test_disabled_flag_preserved_in_config(self):
        """enabled=false 配置应该被正确读取"""
        config = _editorial_config()
        config["ai"]["editorial_pipeline"]["enabled"] = False
        editorial_config = config["ai"]["editorial_pipeline"]
        assert editorial_config.get("enabled") is False

    def test_assignment_respects_allow_multi_flag(self, silent_logger):
        """allow_multi_assign=False 时保持单归属"""
        config = _editorial_config()
        config["ai"]["editorial_pipeline"]["allow_multi_assign"] = False

        candidates = [
            {"title": "文章", "link": "https://example.com/1", "summary": "摘要"},
        ]

        with patch("insightbot.editorial_pipeline._assign_batch_once", return_value={
            "assignments": {"💡 营销行业": candidates, "🤖 数智前沿": []},
            "unassigned": [],
            "record": {"status": "success"},
        }) as mock_assign:
            assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )
            call_kwargs = mock_assign.call_args[1]
            assert call_kwargs["allow_multi"] is False
