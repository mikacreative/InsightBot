from insightbot.task_health_store import clear_task_health, load_task_health, save_task_health


class TestTaskHealthStore:

    def test_save_and_load_task_health(self, tmp_path):
        snapshot = {"task_id": "daily_brief", "checked_at": "2026-04-17T09:00:00+08:00", "counts": {"ok": 1}}
        save_task_health(snapshot, "daily_brief", str(tmp_path))

        loaded = load_task_health("daily_brief", str(tmp_path))
        assert loaded is not None
        assert loaded["task_id"] == "daily_brief"
        assert loaded["counts"]["ok"] == 1

    def test_clear_task_health_removes_file(self, tmp_path):
        save_task_health({"task_id": "daily_brief"}, "daily_brief", str(tmp_path))
        clear_task_health("daily_brief", str(tmp_path))
        assert load_task_health("daily_brief", str(tmp_path)) is None
