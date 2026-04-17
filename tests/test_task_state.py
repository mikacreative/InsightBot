from insightbot.task_state import (
    build_task_revision,
    load_task_state,
    save_task_state,
    touch_revalidation_state,
)


def _base_runtime_config() -> dict:
    return {
        "feeds": {"营销": {"rss": ["https://example.com/feed.xml"], "prompt": "prompt"}},
        "search": {},
        "settings": {"report_title": "日报"},
        "ai": {
            "system_prompt": "sys",
            "selection": {"max_selected_items": 5},
            "editorial_pipeline": {"enabled": True},
        },
        "_task_pipeline": "editorial",
        "_task_channels": ["wecom_main"],
    }


class TestTaskState:

    def test_revision_changes_when_runtime_config_changes(self):
        config = _base_runtime_config()
        revision_a = build_task_revision(config)
        config["feeds"]["营销"]["prompt"] = "new prompt"
        revision_b = build_task_revision(config)
        assert revision_a != revision_b

    def test_touch_revalidation_state_persists_flags(self, tmp_path):
        state = touch_revalidation_state(
            task_id="daily_brief",
            config_revision="abc123",
            needs_revalidation=True,
            bot_dir=str(tmp_path),
        )
        loaded = load_task_state("daily_brief", str(tmp_path))
        assert state["config_revision"] == "abc123"
        assert loaded["needs_revalidation"] is True

    def test_save_and_load_task_state(self, tmp_path):
        save_task_state({"config_revision": "rev1", "needs_revalidation": False}, "daily_brief", str(tmp_path))
        loaded = load_task_state("daily_brief", str(tmp_path))
        assert loaded["config_revision"] == "rev1"
