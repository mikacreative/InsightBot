from insightbot.web_archive import (
    append_archive_record,
    find_archive_record_index,
    get_archive_record,
    list_archive_records,
    update_archive_record_publication,
)
from datetime import datetime


class TestWebArchive:
    def test_append_and_list_archive_records(self, tmp_path):
        record_id = append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "task_name": "每日简报",
                "channel_id": "subscriber_page",
                "title": "每日简报 05-30",
                "markdown": "## 报告内容",
                "created_at": "2026-05-30T08:00:00+08:00",
            },
        )

        records = list_archive_records(bot_dir=str(tmp_path), task_id="daily_brief")

        assert len(records) == 1
        assert records[0]["record_id"] == record_id
        assert records[0]["markdown"] == "## 报告内容"

    def test_list_archive_records_filters_and_sorts_latest_first(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "markdown": "older",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T09:00:00+08:00",
                "markdown": "newer",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "other",
                "created_at": "2026-05-30T10:00:00+08:00",
                "markdown": "other",
            },
        )

        records = list_archive_records(bot_dir=str(tmp_path), task_id="daily_brief")

        assert [item["markdown"] for item in records] == ["newer", "older"]

    def test_get_archive_record_returns_matching_record(self, tmp_path):
        record_id = append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "markdown": "content",
            },
        )

        record = get_archive_record(record_id, bot_dir=str(tmp_path))

        assert record is not None
        assert record["record_id"] == record_id

    def test_list_archive_records_filters_by_datetime_range(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-01T08:00:00+08:00",
                "markdown": "morning",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-02T08:00:00+08:00",
                "markdown": "midday",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-03T08:00:00+08:00",
                "markdown": "evening",
            },
        )

        records = list_archive_records(
            bot_dir=str(tmp_path),
            task_id="daily_brief",
            start_at="2026-06-01T12:00:00+08:00",
            end_at="2026-06-03T07:59:00+08:00",
        )

        assert [item["markdown"] for item in records] == ["midday"]

    def test_list_archive_records_filters_by_datetime_object_range(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-01T08:00:00+08:00",
                "markdown": "morning",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-02T08:00:00+08:00",
                "markdown": "midday",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-06-03T08:00:00+08:00",
                "markdown": "evening",
            },
        )

        start = datetime.fromisoformat("2026-06-02T00:00:00+08:00")
        end = datetime.fromisoformat("2026-06-03T07:00:00+08:00")
        records = list_archive_records(
            bot_dir=str(tmp_path),
            task_id="daily_brief",
            start_at=start,
            end_at=end,
        )

        assert [item["markdown"] for item in records] == ["midday"]

    def test_find_archive_record_index_uses_record_id(self):
        records = [
            {"record_id": "first"},
            {"record_id": "second"},
        ]

        assert find_archive_record_index(records, "second") == 1
        assert find_archive_record_index(records, "missing") == 0

    def test_list_archive_records_filters_by_published_audience(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "audience": "management",
                "publication_status": "published",
                "markdown": "management brief",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:01:00+08:00",
                "audience": "subscriber",
                "publication_status": "published",
                "markdown": "subscriber brief",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:02:00+08:00",
                "audience": "subscriber",
                "publication_status": "draft",
                "markdown": "draft subscriber brief",
            },
        )

        records = list_archive_records(
            bot_dir=str(tmp_path),
            audience="subscriber",
        )

        assert [item["markdown"] for item in records] == ["subscriber brief"]

    def test_public_records_are_visible_to_every_audience(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "visibility": "public",
                "publication_status": "published",
                "markdown": "public brief",
            },
        )

        records = list_archive_records(
            bot_dir=str(tmp_path),
            audience="management",
        )

        assert [item["markdown"] for item in records] == ["public brief"]

    def test_list_archive_records_accepts_multiple_audiences(self, tmp_path):
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "audience": "management",
                "publication_status": "published",
                "markdown": "management brief",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:01:00+08:00",
                "visibility": "public",
                "publication_status": "published",
                "markdown": "public brief",
            },
        )
        append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:02:00+08:00",
                "audience": "subscriber",
                "publication_status": "published",
                "markdown": "subscriber brief",
            },
        )

        records = list_archive_records(
            bot_dir=str(tmp_path),
            audiences=["management", "public"],
        )

        assert [item["markdown"] for item in records] == ["public brief", "management brief"]

    def test_operator_can_unpublish_archive_record(self, tmp_path):
        record_id = append_archive_record(
            str(tmp_path),
            {
                "task_id": "daily_brief",
                "created_at": "2026-05-30T08:00:00+08:00",
                "audience": "subscriber",
                "publication_status": "published",
                "markdown": "visible brief",
            },
        )

        ok = update_archive_record_publication(
            record_id,
            bot_dir=str(tmp_path),
            publication_status="unpublished",
        )

        assert ok is True
        assert list_archive_records(bot_dir=str(tmp_path), audience="subscriber") == []
        record = get_archive_record(record_id, bot_dir=str(tmp_path))
        assert record is not None
        assert record["publication_status"] == "unpublished"
