import json

from insightbot.run_history import (
    append_run_record,
    get_latest_run,
    get_latest_successful_send,
    list_task_runs,
)


class TestRunHistory:

    def test_append_and_get_latest_run(self, tmp_path):
        append_run_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T08:00:00+08:00",
                "dry_run": True,
                "channel_results": [],
            },
        )
        append_run_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T09:00:00+08:00",
                "dry_run": False,
                "channel_results": [{"channel_id": "wecom_main", "ok": True}],
            },
        )

        latest = get_latest_run("daily_brief", str(tmp_path))
        assert latest is not None
        assert latest["started_at"] == "2026-04-17T09:00:00+08:00"

    def test_get_latest_successful_send_ignores_dry_run_and_failures(self, tmp_path):
        records = [
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T08:00:00+08:00",
                "dry_run": True,
                "channel_results": [{"channel_id": "wecom_main", "ok": True}],
            },
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T09:00:00+08:00",
                "dry_run": False,
                "channel_results": [{"channel_id": "wecom_main", "ok": False}],
            },
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T10:00:00+08:00",
                "dry_run": False,
                "channel_results": [{"channel_id": "wecom_main", "ok": True}],
            },
        ]
        for record in records:
            append_run_record(str(tmp_path), record)

        latest_success = get_latest_successful_send("daily_brief", str(tmp_path))
        assert latest_success is not None
        assert latest_success["started_at"] == "2026-04-17T10:00:00+08:00"

    def test_list_task_runs_ignores_bad_json_lines(self, tmp_path):
        append_run_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "started_at": "2026-04-17T08:00:00+08:00",
                "dry_run": True,
                "channel_results": [],
            },
        )
        history_file = tmp_path / "data" / "task_runs.jsonl"
        history_file.write_text(
            history_file.read_text(encoding="utf-8") + "{bad json}\n",
            encoding="utf-8",
        )
        with history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"task_id": "other", "started_at": "2026-04-17T07:00:00+08:00"}) + "\n")

        records = list_task_runs("daily_brief", str(tmp_path), limit=20)
        assert len(records) == 1
        assert records[0]["task_id"] == "daily_brief"
