from insightbot.audit_log import append_audit_event, list_audit_events, redact_audit_changes


class TestAuditLog:
    def test_append_and_list_audit_events_latest_first(self, tmp_path):
        append_audit_event(
            str(tmp_path),
            actor={"name": "运营者", "role": "operator"},
            action="archive.publication.update",
            target={"type": "archive_record", "id": "record-1"},
            changes={"publication_status": "unpublished"},
            created_at="2026-05-30T08:00:00+08:00",
        )
        append_audit_event(
            str(tmp_path),
            actor={"name": "管理员", "role": "admin"},
            action="subscribers.update",
            target={"type": "subscriber", "id": "token-1"},
            changes={"role": "operator"},
            created_at="2026-05-30T09:00:00+08:00",
        )

        events = list_audit_events(bot_dir=str(tmp_path))

        assert [item["action"] for item in events] == [
            "subscribers.update",
            "archive.publication.update",
        ]
        assert events[0]["actor"]["role"] == "admin"

    def test_list_audit_events_filters_action(self, tmp_path):
        append_audit_event(
            str(tmp_path),
            actor={"name": "运营者", "role": "operator"},
            action="archive.publication.update",
            target={"type": "archive_record", "id": "record-1"},
            changes={},
            created_at="2026-05-30T08:00:00+08:00",
        )
        append_audit_event(
            str(tmp_path),
            actor={"name": "管理员", "role": "admin"},
            action="subscribers.update",
            target={"type": "subscriber", "id": "token-1"},
            changes={},
            created_at="2026-05-30T09:00:00+08:00",
        )

        events = list_audit_events(bot_dir=str(tmp_path), action="subscribers.update")

        assert len(events) == 1
        assert events[0]["target"]["id"] == "token-1"

    def test_redact_audit_changes_masks_sensitive_fields(self):
        changes = redact_audit_changes(
            {
                "name": "飞书应用",
                "secret": "wecom-secret",
                "app_secret": "feishu-secret",
                "webhook_url": "https://example.com/hook",
                "nested": {"api_key": "secret-key", "safe": "ok"},
            }
        )

        assert changes == {
            "name": "飞书应用",
            "secret": "***",
            "app_secret": "***",
            "webhook_url": "***",
            "nested": {"api_key": "***", "safe": "ok"},
        }
