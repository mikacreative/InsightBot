# Insight Workbench UI Layering Plan

This note records the current Streamlit-first layout strategy for the human-facing InsightBot workbench.

## Streamlit Partition Tools

From strongest to subtle:

1. `st.tabs`: top-level user modes only. Current modes are `Today`, `Investigate`, and `Configure`.
2. `st.container(border=True)`: visible section boundary for one coherent work unit, such as a send confirmation card.
3. Custom section panels: use sparingly for high-priority decision blocks and status cards.
4. `st.expander`: secondary or developer detail, not the only page structure.
5. `st.columns`: compare a small set of peer metrics or fields on the same conceptual row.
6. `st.divider`: separate major vertical sections when bordered containers would make the page too heavy.
7. `st.caption`: explain local context, not primary instructions.
8. `st.popover`: future candidate for inline help where a field needs explanation but should not take page space.
9. `st.status`: future candidate for live runs, not static status summaries.

## Text Hierarchy

1. Page mode: `Today`, `Investigate`, `Configure`.
2. Page map: one short line showing the sections on the page; each tag should link to the matching section anchor.
3. Section title: emoji plus concrete user action or object, for example `🧭 证据链`.
4. Section copy: one sentence answering why this section exists.
5. Field label: accurate Chinese name; keep technical IDs only where they are actual identifiers.
6. Caption/help: implementation details, warnings, or developer context.

Avoid making `JSON`, `pipeline`, `RunTrace`, or internal codes the first-level vocabulary unless the section is explicitly developer-facing.

## Tab-Level Plan

### Today

Primary goal: answer whether today can run/send.

Sections:

- `✅ 今天判断`: task status, version, channel, dry-run state, and next action.
- `📤 发送确认`: approval card for real send.
- `🧾 最近操作`: last dry-run/send result.
- `🗂️ 运营细节`: folded operational detail.

### Investigate

Primary goal: locate the failing layer.

Sections:

- `🧭 证据链`: source, candidate, output, channel metrics.
- `📌 最近验证`: latest run, latest success, health snapshot.
- `🎯 聚焦板块`: only shown when a section is focused.
- `🧰 Prompt 调试`: folded advanced tool.
- `📜 相关日志`: supporting evidence.

### Configure

Primary goal: make a task runnable without exposing all internals first.

Sections:

- `🧾 基本信息`: task name, schedule, pipeline, channels.
- `🔗 信源`: source names first; URLs and hints inside source cards.
- `📂 栏目`: section names first; keywords, hints, prompt inside cards.
- `🔎 搜索补充`: supplemental search only.
- `🧠 生成策略`: AI selection behavior; default to lower prominence.
- `🔐 变更确认`: apply proposal after review.

Channel and output-format configuration remain in the same `Configure` tab for now, but should keep their own page map and section copy.
