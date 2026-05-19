from insightbot.channel_rendering import (
    FEISHU_APP_SOFT_LIMIT,
    WECOM_SOFT_LIMIT_BYTES,
    build_delivery_plan,
)
from insightbot.channels import FeishuAppChannel, WeChatChannel


class TestDeliveryPlan:
    def test_wecom_splits_long_markdown_into_multiple_messages(self):
        channel = WeChatChannel("wecom_test", "WeCom Test", cid="cid", secret="secret", agent_id="1000001")
        oversized_item = "### 标题\n> " + ("很长的摘要" * 600)
        content = "\n\n".join(["## 💡 营销行业", oversized_item, oversized_item])

        plan = build_delivery_plan(
            channel=channel,
            content=content,
            config={"settings": {"report_title": "日报 {date}"}},
        )

        assert len(plan.messages) >= 2
        assert all(len(message.content.encode("utf-8")) <= WECOM_SOFT_LIMIT_BYTES for message in plan.messages)
        assert plan.messages[0].format == "markdown"
        assert not plan.messages[0].content.startswith("(")
        assert plan.messages[1].content.startswith("(2/")

    def test_feishu_app_uses_interactive_messages(self):
        channel = FeishuAppChannel(
            "feishu_app",
            "飞书应用",
            app_id="cli_xxx",
            app_secret="secret_xxx",
            receive_id="oc_xxx",
            message_template="interactive",
        )
        content = "## 🤖 数智前沿\n\n### 标题\n> 摘要"

        plan = build_delivery_plan(
            channel=channel,
            content=content,
            config={"settings": {"report_title": "日报 {date}"}},
        )

        assert len(plan.messages) == 1
        assert plan.messages[0].format == "interactive"
        assert plan.messages[0].title == plan.title
        assert len(plan.messages[0].content) <= FEISHU_APP_SOFT_LIMIT

    def test_empty_content_returns_single_empty_message(self):
        channel = WeChatChannel("wecom_test", "WeCom Test", cid="cid", secret="secret", agent_id="1000001")

        plan = build_delivery_plan(
            channel=channel,
            content="",
            config={"settings": {"empty_message": "今日为空"}},
        )

        assert len(plan.messages) == 1
        assert plan.messages[0].content == "今日为空"
