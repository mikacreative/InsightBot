from insightbot.task_validation import validate_task_definition


def _base_task_def() -> dict:
    return {
        "name": "每日简报",
        "pipeline": "editorial",
        "feeds": {
            "营销": {
                "rss": ["https://example.com/feed.xml"],
                "keywords": [],
                "prompt": "prompt",
            }
        },
        "channels": ["wecom_main"],
        "schedule": {"hour": 8, "minute": 0},
        "search": {"enabled": False, "queries": []},
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

    def test_not_ready_when_missing_channels_and_feeds(self):
        task_def = _base_task_def()
        task_def["feeds"] = {}
        task_def["channels"] = []

        result = validate_task_definition("daily_brief", task_def, {"channels": {}})

        assert result["is_runnable"] is False
        codes = {item["code"] for item in result["issues"]}
        assert "missing_categories" in codes
        assert "missing_channels" in codes

    def test_warning_when_search_enabled_without_queries(self):
        task_def = _base_task_def()
        task_def["search"] = {"enabled": True, "queries": []}

        result = validate_task_definition(
            "daily_brief",
            task_def,
            {"channels": {"wecom_main": {"type": "wecom"}}},
        )

        assert result["status"] == "needs_attention"
        assert any(item["code"] == "missing_search_queries" for item in result["issues"])
