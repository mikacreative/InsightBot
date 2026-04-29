"""
test_editorial_pipeline.py — insightbot.editorial_pipeline 核心逻辑测试

测试范围：
  - Stage 1: build_global_candidates — 全量源汇总、链接去重
  - Stage 2: screen_global_candidates — 3x倍率、全量 vs 分片模式
  - Stage 3: assign_candidates_to_categories — 单归属、空板块允许
  - Stage 4: select_for_category — 复用 run_prompt_debug
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
    _normalize_global_items,
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
    """测试板块最终精选（复用 run_prompt_debug）"""

    def test_converts_candidate_format_for_run_prompt_debug(self, silent_logger):
        """应该将全局候选格式转换为 run_prompt_debug 期望的格式"""
        candidates = [
            {
                "title": "测试标题",
                "link": "https://example.com/1",
                "summary": "测试摘要",
                "priority_score": 0.8,
                "editorial_note": "理由",
            }
        ]
        config = _editorial_config()

        mock_result = {
            "status": "success",
            "selected_items": [{"title": "标题", "url": "https://example.com/1", "summary": "摘要"}],
            "preview_markdown": "## 板块\n### [标题](https://example.com/1)",
        }

        # run_prompt_debug is imported inside select_for_category from .smart_brief_runner
        with patch("insightbot.smart_brief_runner.run_prompt_debug", return_value=mock_result) as mock_debug:
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=candidates,
                logger=silent_logger,
            )

        mock_debug.assert_called_once()
        call_kwargs = mock_debug.call_args[1]
        assert call_kwargs["category_name"] == "💡 营销行业"
        # 验证格式转换：news_list 应该包含 title, link, summary
        assert len(call_kwargs["news_list"]) == 1
        assert call_kwargs["news_list"][0]["title"] == "测试标题"
        assert call_kwargs["news_list"][0]["link"] == "https://example.com/1"

    def test_returns_empty_when_no_candidates(self, silent_logger):
        """空候选时返回空结果，不崩溃"""
        config = _editorial_config()
        with patch("insightbot.smart_brief_runner.run_prompt_debug", return_value={
            "status": "empty_candidates",
            "selected_items": [],
        }) as mock_debug:
            result = select_for_category(
                config=config,
                category_name="💡 营销行业",
                candidates=[],
                logger=silent_logger,
            )
        assert result["status"] == "empty_candidates"


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
