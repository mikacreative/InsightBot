from insightbot.channel_routes import normalize_channel_routes, route_channel_ids


class TestNormalizeChannelRoutes:
    def test_normalize_legacy_channel_ids(self):
        routes = normalize_channel_routes(["wecom_main", "archive"], {"channels": {}})

        assert routes == [
            {
                "channel_id": "wecom_main",
                "enabled": True,
                "audience": "",
                "purpose": "default",
            },
            {
                "channel_id": "archive",
                "enabled": True,
                "audience": "",
                "purpose": "default",
            },
        ]

    def test_normalize_rich_routes_skips_disabled_entries(self):
        routes = normalize_channel_routes(
            [
                {
                    "channel_id": "exec_chat",
                    "audience": "management",
                    "purpose": "summary",
                },
                {"channel_id": "noise", "enabled": False},
            ],
            {"channels": {}},
        )

        assert routes == [
            {
                "channel_id": "exec_chat",
                "enabled": True,
                "audience": "management",
                "purpose": "summary",
            }
        ]

    def test_normalize_accepts_id_alias_and_recipient_label(self):
        routes = normalize_channel_routes(
            [
                {
                    "id": "subscriber_page",
                    "recipient": "付费订阅者",
                    "purpose": "",
                }
            ],
            {"channels": {}},
        )

        assert routes == [
            {
                "channel_id": "subscriber_page",
                "enabled": True,
                "audience": "付费订阅者",
                "purpose": "default",
            }
        ]

    def test_route_channel_ids_preserves_order(self):
        routes = normalize_channel_routes(
            [
                "wecom_main",
                {"channel_id": "subscriber_page", "purpose": "archive"},
            ],
            {"channels": {}},
        )

        assert route_channel_ids(routes) == ["wecom_main", "subscriber_page"]

    def test_normalize_preserves_publication_controls(self):
        routes = normalize_channel_routes(
            [
                {
                    "channel_id": "subscriber_page",
                    "audience": "paid",
                    "purpose": "archive",
                    "publication_status": "draft",
                    "visibility": "audience",
                }
            ],
            {"channels": {}},
        )

        assert routes[0]["publication_status"] == "draft"
        assert routes[0]["visibility"] == "audience"
