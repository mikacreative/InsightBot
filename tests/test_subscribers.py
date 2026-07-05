import json

from insightbot.subscribers import (
    has_permission,
    hash_token,
    load_subscribers,
    make_subscriber_record,
    resolve_console_actor,
    resolve_subscriber,
    save_subscribers,
)


class TestResolveSubscriber:
    def test_unknown_token_gets_public_access_only(self, tmp_path):
        result = resolve_subscriber("missing", bot_dir=str(tmp_path))

        assert result == {
            "token": "",
            "name": "Public",
            "role": "subscriber",
            "audiences": ["public"],
        }

    def test_token_resolves_subscriber_audiences(self, tmp_path):
        subscribers_file = tmp_path / "subscribers.json"
        subscribers_file.write_text(
            json.dumps(
                {
                    "subscribers": {
                        "token-123": {
                            "name": "管理层读者",
                            "role": "subscriber",
                            "audiences": ["management", "public"],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = resolve_subscriber("token-123", bot_dir=str(tmp_path))

        assert result == {
            "token": "token-123",
            "name": "管理层读者",
            "role": "subscriber",
            "audiences": ["management", "public"],
        }

    def test_token_hash_resolves_without_plaintext_key(self, tmp_path):
        subscribers_file = tmp_path / "subscribers.json"
        subscribers_file.write_text(
            json.dumps(
                {
                    "subscribers": {
                        "subscriber-1": {
                            "name": "哈希订阅者",
                            "role": "subscriber",
                            "audiences": ["paid_subscribers", "public"],
                            "token_hash": hash_token("secret-token"),
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = resolve_subscriber("secret-token", bot_dir=str(tmp_path))

        assert result == {
            "token": "secret-token",
            "name": "哈希订阅者",
            "role": "subscriber",
            "audiences": ["paid_subscribers", "public"],
        }

    def test_make_subscriber_record_hashes_token(self):
        record = make_subscriber_record(
            token="plain-token",
            name="运营者",
            role="operator",
            audiences=["public"],
        )

        assert record["token_hash"] == hash_token("plain-token")
        assert "plain-token" not in json.dumps(record, ensure_ascii=False)

    def test_admin_role_gets_channel_and_permission_controls(self, tmp_path):
        subscribers_file = tmp_path / "subscribers.json"
        subscribers_file.write_text(
            json.dumps(
                {
                    "subscribers": {
                        "admin-token": {
                            "name": "管理员",
                            "role": "admin",
                            "audiences": ["management", "public"],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        actor = resolve_console_actor("admin-token", bot_dir=str(tmp_path))

        assert actor["role"] == "admin"
        assert has_permission(actor, "manage_channels") is True
        assert has_permission(actor, "manage_subscribers") is True
        assert has_permission(actor, "manage_publication") is True

    def test_operator_role_can_manage_publication_but_not_channels(self, tmp_path):
        subscribers_file = tmp_path / "subscribers.json"
        subscribers_file.write_text(
            json.dumps(
                {
                    "subscribers": {
                        "operator-token": {
                            "name": "运营者",
                            "role": "operator",
                            "audiences": ["paid_subscribers", "public"],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        actor = resolve_console_actor("operator-token", bot_dir=str(tmp_path))

        assert actor["role"] == "operator"
        assert has_permission(actor, "manage_publication") is True
        assert has_permission(actor, "manage_channels") is False
        assert has_permission(actor, "manage_subscribers") is False
        assert has_permission(actor, "run_tasks") is True

    def test_subscriber_role_cannot_run_or_manage(self, tmp_path):
        actor = resolve_console_actor("subscriber-token", bot_dir=str(tmp_path))

        assert actor["role"] == "subscriber"
        assert has_permission(actor, "run_tasks") is False
        assert has_permission(actor, "manage_publication") is False
        assert has_permission(actor, "manage_tasks") is False

    def test_console_defaults_to_local_admin_when_no_token_required(self, tmp_path):
        actor = resolve_console_actor("", bot_dir=str(tmp_path), auth_required=False)

        assert actor["role"] == "admin"
        assert has_permission(actor, "manage_channels") is True

    def test_admin_role_has_manage_tasks(self, tmp_path):
        subscribers_file = tmp_path / "subscribers.json"
        subscribers_file.write_text(
            json.dumps(
                {
                    "subscribers": {
                        "admin-token": {
                            "name": "管理员",
                            "role": "admin",
                            "audiences": ["management", "public"],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        actor = resolve_console_actor("admin-token", bot_dir=str(tmp_path))

        assert has_permission(actor, "manage_tasks") is True
        assert has_permission(actor, "run_tasks") is True

    def test_console_falls_back_to_subscriber_when_token_required(self, tmp_path):
        actor = resolve_console_actor("", bot_dir=str(tmp_path), auth_required=True)

        assert actor["role"] == "subscriber"
        assert has_permission(actor, "manage_channels") is False

    def test_save_subscribers_round_trips_config(self, tmp_path):
        payload = {
            "subscribers": {
                "token": {
                    "name": "运营者",
                    "role": "operator",
                    "audiences": ["public"],
                }
            }
        }

        save_subscribers(payload, bot_dir=str(tmp_path))

        assert load_subscribers(str(tmp_path)) == payload
