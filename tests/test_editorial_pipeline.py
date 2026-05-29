"""
test_editorial_pipeline.py — insightbot.editorial_pipeline 核心逻辑测试

测试范围：
  - Stage 1: build_global_candidates — 全量源汇总、链接去重
  - Stage 2: screen_global_candidates — 3x倍率、全量 vs 分片模式
  - Stage 3: assign_candidates_to_categories — 单归属、空板块允许
  - Stage 4: select_for_category — 代码生成 Markdown，AI 只改写摘要
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
    _build_publication_scope_summary,
    _call_global_screen_once,
    _resolve_category_name,
    _normalize_search_result,
    _normalize_global_items,
    _parse_assignment_lines,
    _parse_assignment_response,
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
        raw = "C001 | 0.80 | 理由"
        with patch("insightbot.editorial_pipeline.chat_completion", side_effect=["not json", raw]) as mock_ai:
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
                    system_prompt="只输出行协议",
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
        result = _parse_global_screen_response(
            "C001 | 0.75 | 有价值\nC002 | 0.10 | 排除",
            candidates,
            selection_settings={
                "max_selected_items": 10,
                "title_max_len": 50,
                "summary_max_len": 60,
                "min_priority_score": 0.5,
            },
        )

        assert [item["link"] for item in result] == ["https://example.com/keep"]


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

    def test_resolves_category_without_emoji(self):
        category_list = ["💡 营销行业", "🤖 数智前沿"]
        assert _resolve_category_name("营销行业", category_list) == "💡 营销行业"
        assert _resolve_category_name("数智前沿", category_list) == "🤖 数智前沿"

    def test_assign_batch_accepts_normalized_category_name(self, silent_logger):
        candidates = [
            {"title": "文章1", "link": "https://example.com/1", "summary": "摘要"},
        ]
        config = _editorial_config()

        raw_response = "C001 | 营销行业 | 匹配营销案例"

        with patch("insightbot.editorial_pipeline.chat_completion", return_value=raw_response):
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        assert len(result["category_candidate_map"]["💡 营销行业"]) == 1
        assert result["category_candidate_map"]["💡 营销行业"][0]["assignment_reason"] == "匹配营销案例"
        assert result["unassigned"] == []

    def test_assignment_prefers_source_section_hints(self, silent_logger):
        candidates = [
            {
                "title": "AI营销文章",
                "link": "https://example.com/ai",
                "summary": "摘要",
                "source_section_hints": ["🤖 数智前沿"],
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion") as mock_ai:
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        mock_ai.assert_not_called()
        assert len(result["category_candidate_map"]["🤖 数智前沿"]) == 1
        assert result["category_candidate_map"]["🤖 数智前沿"][0]["assignment_reason"] == "source_section_hints"

    def test_policy_hint_requires_policy_evidence(self, silent_logger):
        candidates = [
            {
                "title": "China Robotaxi Firms Expand Fleet",
                "link": "https://example.com/robotaxi",
                "summary": "Robotaxi companies expand commercial operations.",
                "source_url": "https://www.chinanews.com.cn/cj/2026/05-29/example.shtml",
                "source_section_hints": ["📢 政策导向"],
            },
        ]
        config = _editorial_config()
        config["sections"]["📢 政策导向"] = {
            "keywords": [],
            "source_hints": ["policy"],
            "prompt": "政策导向",
        }

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="NONE") as mock_ai:
            result = assign_candidates_to_categories(
                config=config, screened_candidates=candidates, logger=silent_logger
            )

        mock_ai.assert_called_once()
        assert result["category_candidate_map"]["📢 政策导向"] == []
        assert result["unassigned"][0]["link"] == "https://example.com/robotaxi"

    def test_assignment_parser_extracts_json_from_surrounding_text(self):
        raw = '输出：{"assignments":[{"candidate_index":1,"assigned_category":"💡 营销行业","reason":"匹配"}]}'
        assignments = _parse_assignment_response(raw)
        assert assignments == [
            {"candidate_index": 1, "assigned_category": "💡 营销行业", "reason": "匹配"}
        ]

    def test_assignment_line_parser_extracts_minimal_contract(self):
        assignments = _parse_assignment_lines(
            "C001 | 营销行业 | 匹配\nC002 | 数智前沿 | AI应用",
            {"C001", "C002"},
            ["💡 营销行业", "🤖 数智前沿"],
        )
        assert assignments == [
            {"ref": "C001", "assigned_category": "💡 营销行业", "reason": "匹配"},
            {"ref": "C002", "assigned_category": "🤖 数智前沿", "reason": "AI应用"},
        ]


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
    """测试板块最终输出：代码拥有标题、链接和 Markdown，AI 只改写摘要"""

    def test_uses_code_owned_title_url_and_ai_summary(self, silent_logger):
        """标题、链接和 Markdown 应该由代码生成，AI 只提供摘要。"""
        candidates = [
            {
                "title": "[RSS] 文章频道 - 测试标题",
                "link": "https://example.com/1",
                "summary": "测试摘要",
                "priority_score": 0.8,
                "editorial_note": "理由",
            }
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | 改写后的摘要") as mock_ai:
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        mock_ai.assert_called_once()
        assert mock_ai.call_args[1]["json_mode"] is False
        assert result["status"] == "success"
        assert result["selected_items"] == [
            {"title": "测试标题", "url": "https://example.com/1", "summary": "改写后的摘要"}
        ]
        assert "### [测试标题](https://example.com/1)" in result["preview_markdown"]

    def test_does_not_fill_to_five_below_final_quality_threshold(self, silent_logger):
        candidates = [
            {
                "title": title,
                "link": f"https://example.com/{i}",
                "summary": "摘要",
                "priority_score": score,
            }
            for i, (title, score) in enumerate(
                [
                    ("苹果推出新广告", 0.91),
                    ("耐克发布跑步社群计划", 0.82),
                    ("普通行业消息", 0.69),
                    ("低价值消息", 0.6),
                    ("边缘消息", 0.55),
                ],
                start=1,
            )
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | 摘要一\nC002 | 摘要二"):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["status"] == "success"
        assert len(result["selected_items"]) == 2
        assert [item["title"] for item in result["selected_items"]] == ["苹果推出新广告", "耐克发布跑步社群计划"]

    def test_policy_final_gate_drops_non_policy_items(self, silent_logger):
        candidates = [
            {
                "title": "智博会观察：具身智能独立成馆",
                "link": "https://example.com/embodied-ai",
                "summary": "具身智能产业地位提升。",
                "priority_score": 0.9,
            },
            {
                "title": "中国两部门系统布局人工智能计量能力建设",
                "link": "https://example.com/ai-measurement",
                "summary": "两部门联合印发人工智能计量体系文件。",
                "priority_score": 0.86,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | AI计量摘要"):
            result = select_for_category(
                config=config,
                category_name="📢 政策导向",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1
        assert result["selected_items"][0]["title"] == "中国两部门系统布局人工智能计量能力建设"

    def test_policy_final_gate_ignores_broad_governance_terms(self, silent_logger):
        candidates = [
            {
                "title": "王毅出席全球治理之友小组会议",
                "link": "https://example.com/global-governance",
                "summary": "国际会议讨论全球治理合作。",
                "priority_score": 0.92,
            },
            {
                "title": "上海市网信办通报13品牌违规收集个人信息",
                "link": "https://example.com/privacy",
                "summary": "消费品牌需关注个人信息合规。",
                "priority_score": 0.88,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | 数据合规摘要"):
            result = select_for_category(
                config=config,
                category_name="📢 政策导向",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1
        assert result["selected_items"][0]["title"] == "上海市网信办通报13品牌违规收集个人信息"

    def test_policy_final_gate_requires_business_relevance(self, silent_logger):
        candidates = [
            {
                "title": "生态环境部印发海湾清洁指数评价技术方法",
                "link": "https://example.com/bay-cleanliness",
                "summary": "生态环境部印发海湾清洁指数评价技术方法试行文件。",
                "priority_score": 0.9,
            },
            {
                "title": "高考临近多家AI平台涉考功能限时上锁",
                "link": "https://example.com/ai-exam",
                "summary": "高考期间多家AI平台限制涉考功能。",
                "priority_score": 0.88,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | AI合规摘要"):
            result = select_for_category(
                config=config,
                category_name="📢 政策导向",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1
        assert result["selected_items"][0]["title"] == "高考临近多家AI平台涉考功能限时上锁"

    def test_digital_final_gate_requires_product_or_ai_signal(self, silent_logger):
        candidates = [
            {
                "title": "当你没有付费，你可能就是产品本身",
                "link": "https://example.com/free-product",
                "summary": "互联网平台免费服务背后用户成为产品，AI时代数据与注意力被商业化利用。",
                "assignment_reason": "平台数据议题",
                "priority_score": 0.91,
            },
            {
                "title": "亚马逊搜索全面 AI 化",
                "link": "https://example.com/amazon-ai-search",
                "summary": "电商搜索被AI重构。",
                "priority_score": 0.86,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | AI搜索摘要"):
            result = select_for_category(
                config=config,
                category_name="🤖 数智前沿",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1
        assert result["selected_items"][0]["title"] == "亚马逊搜索全面 AI 化"

    def test_digital_final_gate_allows_platform_product_changes(self, silent_logger):
        candidates = [
            {
                "title": "小红书买下世界杯版权",
                "link": "https://example.com/rednote-worldcup",
                "summary": "小红书通过版权内容拓展平台内容供给。",
                "priority_score": 0.88,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | 平台内容摘要"):
            result = select_for_category(
                config=config,
                category_name="🤖 数智前沿",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1

    def test_marketing_final_gate_drops_pure_tech_expo(self, silent_logger):
        candidates = [
            {
                "title": "智博会观察：具身智能独立成馆",
                "link": "https://example.com/embodied-ai",
                "summary": "人工智能产业博览会展示具身智能技术进展。",
                "priority_score": 0.91,
            },
            {
                "title": "六神把发布会开成蚊学院",
                "link": "https://example.com/sixgod",
                "summary": "品牌通过场景化发布会强化新品传播。",
                "priority_score": 0.86,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="C001 | 发布会摘要"):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert len(result["selected_items"]) == 1
        assert result["selected_items"][0]["title"] == "六神把发布会开成蚊学院"

    def test_raw_excerpt_fallback_uses_code_owned_summary(self, silent_logger):
        candidates = [
            {
                "title": "淘小宝勇闯异世界",
                "link": "https://example.com/pet",
                "summary": "这几年被大量铲屎官们加倍宠爱的，非异宠们莫属了！今年5月7日-10日，在上海国家会展中心举办活动。",
                "priority_score": 0.88,
            },
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", return_value="NONE"):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["selected_items"][0]["summary"] == "淘小宝勇闯异世界，需关注其对品牌传播与消费沟通的影响。"

    def test_summary_parser_rejects_none_and_strips_markdown(self):
        parsed = _parse_summary_lines(
            "C001 | NONE\nC002 | 💡 *有效摘要内容*",
            {"C001", "C002"},
            summary_max_len=50,
        )
        assert parsed == {"C002": "有效摘要内容"}

    def test_cross_category_dedupe_drops_repeated_topics(self):
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
        """空候选时返回空结果，不崩溃"""
        config = _editorial_config()
        result = select_for_category(
            config=config,
            category_name="💡 营销行业",
            candidates=[],
            logger=silent_logger,
        )
        assert result["status"] == "empty_candidates"

    def test_falls_back_to_original_summary_when_ai_rewrite_fails(self, silent_logger):
        candidates = [
            {
                "title": "测试标题",
                "link": "https://example.com/1",
                "summary": "原始摘要内容",
                "priority_score": 0.8,
            }
        ]
        config = _editorial_config()

        with patch("insightbot.editorial_pipeline.chat_completion", side_effect=TimeoutError("timeout")):
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        assert result["status"] == "success"
        assert result["selected_items"][0]["summary"] == "原始摘要内容"
        assert result["batches"][0]["status"] == "error"


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
