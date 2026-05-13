from insightbot.task_validation import validate_task_definition


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
