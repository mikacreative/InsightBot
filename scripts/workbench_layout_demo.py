from __future__ import annotations

import streamlit as st

try:
    from scripts.ui.workbench_layout import (
        bordered_section,
        render_page_map,
        render_section_heading,
        render_section_note,
        render_workbench_styles,
    )
except ModuleNotFoundError:
    from ui.workbench_layout import (
        bordered_section,
        render_page_map,
        render_section_heading,
        render_section_note,
        render_workbench_styles,
    )


def main() -> None:
    st.set_page_config(page_title="InsightBot UI Layering Demo", layout="wide")
    render_workbench_styles()
    st.title("InsightBot UI Layering Demo")
    st.caption("小范围验证 Streamlit 页面分层：不接真实任务、不写配置，只看信息层级。")

    today, investigate, configure = st.tabs(["Today", "Investigate", "Configure"])

    with today:
        render_page_map(
            "本页板块",
            [
                ("✅ 今天判断", "demo-today-decision"),
                ("📊 关键证据", "demo-today-evidence"),
                ("📤 发送确认", "demo-today-send"),
                ("🗂️ 运营细节", "demo-today-details"),
            ],
        )
        with bordered_section("✅ 今天判断", "第一眼只回答：今天是否可以推送，以及下一步应该做什么。", anchor="demo-today-decision"):
            cols = st.columns([1.4, 1, 1, 1])
            cols[0].metric("任务状态", "Ready")
            cols[1].metric("配置版本", "v20260609")
            cols[2].metric("发送前检查", "建议 Dry Run")
            cols[3].metric("目标频道", "企业微信")
            render_section_note("建议路径：先 Dry Run，确认输出预览后再进入发送确认。")

        render_section_heading("📊 关键证据", "把配置版本、最近运行和信源状态放在一张轻量证据卡里。", anchor="demo-today-evidence")
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("最近运行", "今天 08:30")
            c2.metric("信源状态", "28/32 OK")
            c3.metric("输出预览", "可用")

        render_section_heading("📤 发送确认", "高风险动作独立成卡；没有确认前不触发真实发送。", anchor="demo-today-send")
        with st.container(border=True):
            st.write("任务：营销早报")
            st.write("目标：测试企业微信群")
            st.warning("当前还没有最新 Dry Run 证据。")
            st.columns(2)[0].button("确认发送", disabled=True, use_container_width=True)

        with st.expander("🗂️ 运营细节", expanded=False):
            st.markdown('<div id="demo-today-details"></div>', unsafe_allow_html=True)
            st.write("调度、上次成功发送、历史运行摘要等低频信息放在这里。")

    with investigate:
        render_page_map(
            "本页板块",
            [
                ("🧭 证据链", "demo-investigate-chain"),
                ("⚠️ 异常信源", "demo-investigate-sources"),
                ("📝 输出预览", "demo-investigate-output"),
                ("🧰 高级调试", "demo-investigate-debug"),
            ],
        )
        render_section_heading("🧭 证据链", "用一行流程指标定位问题卡在哪里，而不是先看日志。", anchor="demo-investigate-chain")
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1. 信源", "28/32 OK", delta="4 error", delta_color="inverse")
            c2.metric("2. 候选", "92 -> 18")
            c3.metric("3. 输出", "有预览")
            c4.metric("4. 发送", "未发送")

        with st.expander("⚠️ 异常信源", expanded=False):
            st.markdown('<div id="demo-investigate-sources"></div>', unsafe_allow_html=True)
            st.write("madbrief.com/feed | SSL error")
            st.write("localhost:1200/36kr | timeout")

        render_section_heading("📝 输出预览", "最终发送内容在这里预览；原始日志不进入第一屏。", anchor="demo-investigate-output")
        with st.container(border=True):
            st.markdown("### 六神：把发布会开成「蚊」学院\n> 场景化活动强化品牌认知。")

        with st.expander("🧰 高级调试", expanded=False):
            st.markdown('<div id="demo-investigate-debug"></div>', unsafe_allow_html=True)
            st.code("RunTrace / stage_counts / raw prompt debug stay here.", language="text")

    with configure:
        render_page_map(
            "本页板块",
            [
                ("🧾 基本信息", "demo-config-basics"),
                ("🔗 信源", "demo-config-sources"),
                ("📂 栏目", "demo-config-sections"),
                ("🔎 搜索补充", "demo-config-search"),
                ("🧠 生成策略", "demo-config-strategy"),
                ("🔐 变更确认", "demo-config-approval"),
            ],
        )
        render_section_heading("🧾 基本信息", "只放任务名、调度和目标频道。复杂项不放在第一屏。", anchor="demo-config-basics")
        with st.container(border=True):
            cols = st.columns([1.3, 1, 1, 1.5])
            cols[0].text_input("任务名称", value="营销早报")
            cols[1].selectbox("生成流程", ["智能编辑流程（推荐）", "传统规则流程"])
            cols[2].number_input("小时", 0, 23, 8)
            cols[3].multiselect("目标频道", ["测试企业微信群（企业微信机器人）"])

        render_section_heading("🔗 信源", "默认只展示信源名称；URL、栏目提示等细节进入单个信源卡片。", anchor="demo-config-sources")
        with st.container(border=True):
            st.expander("🔗 数英网", expanded=False).text_input("RSS URL", value="https://www.digitaling.com/rss")
            st.expander("🔗 36 氪热榜", expanded=False).text_input("RSS URL", value="http://localhost:1200/36kr/hot-list")

        render_section_heading("📂 栏目", "栏目名称和筛选意图分开看；复杂 prompt 默认折叠。", anchor="demo-config-sections")
        with st.container(border=True):
            st.write("💡 营销行业 | 🤖 数智前沿 | 📢 政策导向")

        render_section_heading("🔎 搜索补充", "搜索源是补充能力，不和 RSS 信源混在同一屏。", anchor="demo-config-search")
        with st.container(border=True):
            st.selectbox("搜索引擎", ["百度搜索", "关闭搜索补充"])

        st.markdown('<div id="demo-config-strategy"></div>', unsafe_allow_html=True)
        with st.expander("🧠 生成策略：AI 怎么筛选和分配", expanded=False):
            st.slider("候选放大倍率", 1, 8, 3)
            st.toggle("同一条可进多个栏目", value=False)

        render_section_heading("🔐 变更确认", "保存前把变更摘要、风险和版本基线说明清楚。", anchor="demo-config-approval")
        with st.container(border=True):
            st.info("当前没有待确认变更。")


if __name__ == "__main__":
    main()
