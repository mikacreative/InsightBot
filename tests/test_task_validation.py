from insightbot.task_validation import validate_task_definition
from scripts.app import (
    _apply_task_editor_payload,
    _get_task_feeds_view,
    _get_task_search_config,
    _get_task_sections,
    _get_task_sources,
    _normalize_editable_search_query,
)


def _base_task_def() -> dict:
    return {
        "name": "每日简报",
        "pipeline": "editorial",
        "sources": {
            "rss": [
                {
                    "id": "marketing_feed",
                    "url": "https://example.com/feed.xml",
                    "enabled": True,
                    "tags": ["marketing"],
                    "section_hints": ["营销"],
                }
            ],
            "search": {"enabled": False, "queries": []},
        },
        "sections": {
            "营销": {
                "keywords": [],
                "source_hints": ["marketing"],
                "prompt": "prompt",
            }
        },
        "channels": ["wecom_main"],
        "schedule": {"hour": 8, "minute": 0},
        "pipeline_config": {"global_shortlist_multiplier": 3},
    }


class TestTaskValidation:

    def test_ready_when_required_fields_exist(self):
        result = validate_task_definition(
            "daily_brief",
            _base_task_def(),
            {"channels": {"wecom_main": {"type": "wecom"}}},
        )
        assert result["is_runnable"] is True
        assert result["status"] == "ready"

    def test_not_ready_when_missing_channels_and_sections(self):
        task_def = _base_task_def()
        task_def["sources"] = {"rss": [], "search": {"enabled": False, "queries": []}}
        task_def["sections"] = {}
        task_def["channels"] = []

        result = validate_task_definition("daily_brief", task_def, {"channels": {}})

        assert result["is_runnable"] is False
        codes = {item["code"] for item in result["issues"]}
        assert "missing_sections" in codes
        assert "missing_channels" in codes

    def test_warning_when_search_enabled_without_queries(self):
        task_def = _base_task_def()
        task_def["sources"]["search"] = {"enabled": True, "provider": "baidu", "queries": []}

        result = validate_task_definition(
            "daily_brief",
            task_def,
            {"channels": {"wecom_main": {"type": "wecom"}}},
        )

        assert result["status"] == "needs_attention"
        assert any(item["code"] == "missing_search_queries" for item in result["issues"])

    def test_search_query_count_accepts_legacy_string_queries(self):
        task_def = _base_task_def()
        task_def["search"] = {"enabled": True, "queries": [" AI marketing trend ", ""]}

        result = validate_task_definition(
            "daily_brief",
            task_def,
            {"channels": {"wecom_main": {"type": "wecom"}}},
        )

        assert result["status"] == "ready"
        assert result["summary"]["search_query_count"] == 1

    def test_editable_search_query_accepts_legacy_string_queries(self):
        assert _normalize_editable_search_query(" AI marketing trend ") == {
            "keywords": " AI marketing trend ",
            "category_hint": "",
            "max_results": 10,
        }

    def test_task_editor_helpers_read_current_sources_sections_schema(self):
        task_def = _base_task_def()

        assert _get_task_sources(task_def)["rss"][0]["url"] == "https://example.com/feed.xml"
        assert "营销" in _get_task_sections(task_def)
        assert _get_task_feeds_view(task_def)["营销"]["rss"] == ["https://example.com/feed.xml"]
        assert _get_task_search_config(task_def) == {"enabled": False, "queries": []}

    def test_task_editor_payload_saves_back_to_sources_sections_schema(self):
        task_def = _base_task_def()

        updated = _apply_task_editor_payload(
            task_def,
            feeds_editor={
                "品牌营销": {
                    "rss": ["https://example.com/brand.xml"],
                    "keywords": ["AI", "营销"],
                    "prompt": "pick relevant brand moves",
                }
            },
            search_config={
                "enabled": True,
                "provider": "bocha",
                "queries": [{"keywords": "AI 营销", "category_hint": "品牌营销", "max_results": 5}],
            },
        )

        assert "feeds" not in updated
        assert "search" not in updated
        assert updated["sources"]["rss"][0]["url"] == "https://example.com/brand.xml"
        assert updated["sources"]["search"]["queries"] == [
            {"keywords": "AI 营销", "section_hints": ["品牌营销"], "max_results": 5}
        ]
        assert updated["sections"]["品牌营销"]["prompt"] == "pick relevant brand moves"
