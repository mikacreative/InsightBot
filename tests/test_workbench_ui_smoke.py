from __future__ import annotations

from pathlib import Path
import re


def _assert_anchor_targets_exist(source: str, anchors: list[str]) -> None:
    for anchor in anchors:
        assert f'anchor="{anchor}"' in source or f'id="{anchor}"' in source


def test_streamlit_app_declares_three_workbench_views():
    source = Path("scripts/app.py").read_text(encoding="utf-8")

    assert 'st.tabs([\n        "Today",\n        "Investigate",\n        "Configure",' in source
    assert "今天能不能推送？" in source
    assert "发送确认卡" in source
    assert "本页板块" in source
    assert "render_page_map" in source
    assert "render_section_heading" in source
    assert '"today-decision"' in source
    assert '"configure-basics"' in source
    assert '"investigate-chain"' in source
    assert "pending_send::" in source
    assert "准备发送确认" in source
    assert "Configure / 任务设置" in source
    assert "Configure / 频道" in source
    assert "Configure / 输出版式" in source
    assert "Investigate / 排查" in source
    assert "Investigate / 深度日志" in source


def test_streamlit_app_uses_product_task_card_view_model():
    source = Path("scripts/app.py").read_text(encoding="utf-8")

    assert "from insightbot.product import build_change_proposal, build_task_card" in source
    assert "workspace_state = scheduler.build_workspace_state_command(selected_task_id)" in source
    assert "workspace_state=workspace_state" in source
    assert "证据链：从信源到发送" in source
    assert "1. 信源" in source
    assert "2. 候选" in source
    assert "变更确认卡" in source
    assert "approve_and_apply_changeset" in source
    assert 'st.session_state[f"pending_changeset::{task_id}"]' in source
    assert "Add RSS source from Workbench" in source
    assert "Update section prompt from Workbench" in source


def test_streamlit_app_uses_human_readable_option_labels():
    source = Path("scripts/app.py").read_text(encoding="utf-8")

    assert "PIPELINE_LABELS" in source
    assert '"editorial": "智能编辑流程（推荐）"' in source
    assert "SEARCH_PROVIDER_LABELS" in source
    assert '"baidu": "百度搜索"' in source
    assert "CHANNEL_TYPE_LABELS" in source
    assert '"wecom": "企业微信机器人"' in source
    assert '"feishu_app": "飞书应用消息"' in source
    assert "format_channel_option" in source
    assert "format_func=label_for(PIPELINE_LABELS)" in source
    assert "format_func=label_for(SEARCH_PROVIDER_LABELS)" in source
    assert "format_func=label_for(CHANNEL_TYPE_LABELS)" in source


def test_workbench_layout_demo_and_plan_exist():
    demo = Path("scripts/workbench_layout_demo.py").read_text(encoding="utf-8")
    helper = Path("scripts/ui/workbench_layout.py").read_text(encoding="utf-8")
    plan = Path("docs/workbench_ui_layering_plan.md").read_text(encoding="utf-8")

    assert "InsightBot UI Layering Demo" in demo
    assert "st.container(border=True)" in demo
    assert "render_page_map" in demo
    assert "def render_page_map" in helper
    assert "def bordered_section" in helper
    assert 'href="#{escape(anchor)}"' in helper
    assert "def make_anchor_id" in helper
    assert "escape(text)" in helper
    assert "Streamlit Partition Tools" in plan
    assert "`st.container(border=True)`" in plan
    assert "Text Hierarchy" in plan
    assert "each tag should link to the matching section anchor" in plan
    assert "🧾 基本信息" in plan


def test_workbench_layout_demo_page_map_anchors_have_targets():
    demo = Path("scripts/workbench_layout_demo.py").read_text(encoding="utf-8")
    anchors = sorted(set(re.findall(r'"(demo-[a-z0-9-]+)"', demo)))

    _assert_anchor_targets_exist(demo, anchors)


def test_gateway_readiness_checklist_exists():
    source = Path("docs/gateway_readiness_checklist.md").read_text(encoding="utf-8")

    assert "Public route: `/insightbot/`" in source
    assert "127.0.0.1:8501" in source
    assert "Browser requests do not call `http(s)://<host>:8501`" in source
