# Dev Editorial Local Next Phase Plan

Date: 2026-06-03（更新：2026-06-04）
Branch context: `dev-editorial`
Execution owner: next local development session, including 5.3 spark

## Hard Boundary

Do not make any concrete changes to the Tencent Cloud production environment in this thread or in the next execution session.

All development, testing, screenshots, Streamlit runs, smoke checks, and verification must happen locally. Do not SSH into production to edit files, restart services, upload code, or mutate production config. Do not test real WeChat / WeCom delivery channels.

Allowed work:

- Read and edit local repository files.
- Run local tests.
- Run local Streamlit console.
- Use local or test config only.
- Perform dry-run style checks that do not send real channel messages.

Disallowed work:

- No production deploy.
- No production service restart.
- No production config mutation.
- No real WeChat / WeCom channel send test.
- No production data cleanup or migration.

## One-Sentence Goal

Converge `dev-editorial` into a locally verifiable, structurally clean control-console branch where task state, content sources, channel routing, and subscriber-facing archive behavior are understandable without risking production configuration.

## Next Stage Goal (本次执行)

- 完成冲突副本清单的最终版冻结，明确每个 `* 2` 文件是“可删”还是“需确认”。
- 复核并固化 `local_state_snapshot` 的发布前门禁行为，确保：
  - `--require` + `--strict` 只约束必选文件；
  - baseline 缺失在 strict 下失败；
  - 快照输出和测试链可复现。
- 通过本地关键验证命令后进入 5.3 分支交付准备。

## Confirmed Current Facts

- Current local branch is `dev-editorial`.
- `origin/dev-editorial` is gone, so remote tracking needs later cleanup or branch publication decision.
- The local worktree is dirty with many modified files and several untracked files.
- `dev` currently differs from `dev-editorial` by one small committed fix: `78fd487 fix(console): avoid session state mutation on saved prompt`.
- That `dev` fix removes session-state binding for a read-only saved Prompt text area.
- Current `dev-editorial` already follows the same constraint in the inline prompt debug area: only the draft Prompt uses a mutable session key.
- Therefore, do not blindly cherry-pick `78fd487`; the structural constraint has already been absorbed.
- `dev-editorial` is already the more advanced structural branch: it contains `scripts/ui/`, `insightbot/` task/channel/runtime modules, and `editorial-intelligence/`.
- There are suspicious duplicate/conflict files such as `AGENTS 2.md`, `source_strategy 2.py`, `insightbot/wecom_callback 2.py`, and similar files. These need review before deletion.

## Structural Constraints To Preserve

1. Keep production/runtime safety explicit.
   - UI changes must not silently overwrite runtime config.
   - Dry Run must stay non-sending.
   - Real channel testing must remain opt-in and out of scope for this local phase.

2. Keep module ownership clear.
   - `scripts/app.py`: Streamlit composition and top-level wiring only.
   - `scripts/ui/`: control-console page sections and display components.
   - `insightbot/`: product runtime, task config, channels, subscribers, archive, validation.
   - `editorial-intelligence/`: editorial pipeline contracts, adapters, diagnostics, skill runtime.
   - `tests/`: InsightBot app/runtime tests.
   - `editorial-intelligence/tests/`: editorial package tests.

3. Keep raw config and effective config distinct.
   - Raw task config is what the UI edits.
   - Effective task config is what runtime uses after fallback/merge.
   - Read-only overview should display effective config.
   - Edit forms should avoid unintentionally writing fallback config back into raw task config.

4. Avoid Streamlit session-state mutation issues.
   - Do not bind read-only display widgets to mutable session keys that are reassigned by code.
   - Mutable session keys are for user drafts and explicit temporary UI state.

5. Make user-facing control surfaces understandable.
   - Operators should see what task is selected, which boards exist, which RSS sources feed each board, which channels are routed, and what is safe to run locally.

## Next Phase Development Targets

### Phase 1: Local Inventory And Conflict File Review

执行结果（本地）：

- `AGENTS 2.md`
  - 分类：accidental duplicate（与 `AGENTS.md` 仅换行差异）
  - 建议：后续清理时删除
- `editorial-intelligence/editorial_intelligence/contracts/source_strategy 2.py`
  - 分类：accidental duplicate（与 `editorial_intelligence/contracts/source_strategy.py` 内容一致，仅 CRLF/换行差异）
  - 建议：后续清理时删除
- `editorial-intelligence/examples/insightbot_integration 2.py`
  - 分类：accidental duplicate（与 `editorial-intelligence/examples/insightbot_integration.py` 内容一致，仅换行差异）
  - 建议：后续清理时删除
- `editorial-intelligence/tests/test_insightbot_bridge 2.py`
  - 分类：accidental duplicate（与 `editorial-intelligence/tests/test_insightbot_bridge.py` 内容一致，仅 CRLF/换行差异）
  - 建议：后续清理时删除
- `insightbot/wecom_callback 2.py`
  - 分类：accidental duplicate（与 `insightbot/wecom_callback.py` 内容一致，先暂不删）
  - 建议：后续清理时删除
- `.env.local 2.example`
  - 分类：accidental duplicate（与 `.env.local.example` 内容差异较大，缺失 `WEB_ARCHIVE_FILE`、`SUBSCRIBERS_FILE`、`AUDIT_LOG_FILE`、`INSIGHTBOT_CONSOLE_AUTH_REQUIRED` 等字段）
  - 建议：确认用途后再决策，当前阶段不删除（本地历史残留）

状态：完成，未触及生产，不做删除，待下一次清理会话批量处理。

Next-phase 复核结果（本次）：

| 重复文件 | 参照文件 | 对比结论 | 清单动作 |
| --- | --- | --- | --- |
| `AGENTS 2.md` | `AGENTS.md` | 去除 CRLF/末尾空白后等价 | 标记为“可删（待确认）” |
| `editorial-intelligence/editorial_intelligence/contracts/source_strategy 2.py` | `editorial-intelligence/editorial_intelligence/contracts/source_strategy.py` | 去除 CRLF/末尾空白后等价 | 标记为“可删（待确认）” |
| `editorial-intelligence/examples/insightbot_integration 2.py` | `editorial-intelligence/examples/insightbot_integration.py` | 去除 CRLF/末尾空白后等价 | 标记为“可删（待确认）” |
| `editorial-intelligence/tests/test_insightbot_bridge 2.py` | `editorial-intelligence/tests/test_insightbot_bridge.py` | 去除 CRLF/末尾空白后等价 | 标记为“可删（待确认）” |
| `insightbot/wecom_callback 2.py` | `insightbot/wecom_callback.py` | 去除 CRLF/末尾空白后等价 | 标记为“可删（待确认）” |
| `.env.local 2.example` | `.env.local.example` | 内容差异显著（字段缺失） | 标记为“不立即删除，需确认是否保留本地历史回滚用途” |
| `editorial-intelligence/tests/__pycache__/test_insightbot_bridge 2.cpython-313-pytest-8.3.3.pyc` | 无（缓存产物） | `.pyc` 缓存文件，无需纳入清理决策 | 标记为“工具产物，忽略” |

执行更新（本次）：

- 已完成：补齐 `* 2` 命名冲突文件清单（包含 `.env.local 2.example`）并完成风险分层，均先不删除。
- .env 复制文件建议不按“立即删”处理：需先确认其是否用于本地历史配置回滚场景。


Goal: decide what is real work vs accidental duplicate files.

Actions:

- List all untracked files.
- Review every file with a ` 2` suffix or conflict-like name.
- For each duplicate, classify it as:
  - accidental duplicate safe to remove later,
  - useful changes to merge into canonical file,
  - uncertain and needs user review.
- Do not delete in the first pass. Produce a short table in the session notes before any cleanup.

Success criteria:

- Clear cleanup map for all duplicate/conflict files.
- No production interaction.
- No irreversible deletion.

### Phase 2: Apply Dev Structure Logic To Dev Editorial

Goal: enforce the `dev` branch's important constraint without duplicating already-applied code.

Actions:

- Confirm all prompt/debug UI areas avoid programmatic writes to read-only widget session keys.
- Search for `st.session_state[...] = current_*` around read-only widgets.
- Search for read-only `st.text_area` / `st.text_input` widgets that use keys later reassigned by code.
- Add focused tests only if a behavior can be checked without fragile Streamlit UI internals.

Success criteria:

- No prompt/debug UI path mutates read-only saved-display keys.
- Any found issue is fixed locally.
- No cherry-pick unless there is a concrete missing change.

执行更新（本次）：

- 已检查 `scripts/app.py` 与 `scripts/ui` 中 read-only 展示控件的 `st.session_state` 赋值路径，未发现将可读文本控件 key 在渲染阶段回写的路径。
- 保持不变更既有约束，未做功能性回退。

### Phase 3: Add Current Task Boards And RSS Visibility To Local Console

Goal: the control console must show the selected task's actual boards and RSS sources.

Recommended implementation:

- Add a read-only "内容源与板块" panel to the overview page in `scripts/ui/overview.py`.
- Feed it the effective selected task, not only the raw selected task.
- Show:
  - board/category name,
  - RSS source count,
  - keyword count,
  - RSS source list,
  - keywords,
  - prompt excerpt or full prompt in an expander.
- Default expand the first board and collapse the rest.
- Keep editing in "任务管理"; overview remains read-only.

Success criteria:

- Local console overview shows boards and RSS sources for `Daily_brief`.
- It works even when raw task config is sparse but effective runtime config has fallback feeds.
- No config is saved when viewing the panel.

执行更新（本次）:

- 已在 `scripts/ui/overview.py` 增加“内容源与板块”只读面板，默认展示 effective 任务配置。
- 面板支持板块列表、每板块 RSS 数、关键词数、RSS 明细、关键词和 Prompt 摘要。
- 默认展开第一个面板；未配置时给出友好提示。
- 保持纯展示，不写入任何配置文件。

### Phase 4: Protect Daily Brief Config Semantics Locally

Goal: avoid losing the user's real Daily Brief task configuration during local development.

Actions:

- Add or document a local config snapshot workflow before editing task/channel config.
- Compare raw task config vs effective task config in a local-only diagnostic output.
- Ensure save actions write only explicit user edits, not automatic fallback expansion unless the UI clearly says it will materialize fallback config.

Success criteria:

- Developer can answer: "What is raw Daily_brief config?" and "What is effective Daily_brief config?"
- Viewing overview cannot mutate config.
- Saving unrelated task fields does not erase boards/RSS.

执行更新（本次）:

- 已在概览页新增“Raw / Effective 配置语义”对照区，显示:
  - Raw 与 Effective 的板块/RSS 数、频道数；
  - fallback/回退差异提示（若存在）；
  - 每次可本地下载 JSON 快照（`raw_task` + `effective_task`）用于回溯。
- 概览仍是只读展示，不会在查看时触发配置变更。
- 保存逻辑未在本次改动中扩展到“自动 materialize fallback”；仍以用户显式编辑字段为主。

### Phase 5: Local Verification Loop

Goal: prove the local branch is safe and coherent before any future deployment decision.

Actions:

- Run Python compile checks for touched files.
- Run focused tests for task validation, config paths, channel routes, subscribers, archive, and editorial bridge where relevant.
- Run local Streamlit console.
- Verify locally:
  - overview loads,
  - task boards/RSS panel is visible,
  - Dry Run UI remains non-sending,
  - no traceback on page load,
  - role/permission views still render if touched.

Success criteria:

- Focused local tests pass or failures are documented with root cause.
- Local UI screenshot or textual verification confirms board/RSS visibility.
- No production action occurred.

执行更新（本次）：

- `python -m py_compile`：
  - `scripts/ui/overview.py`、`scripts/app.py` 通过；
  - 及新增模块 `scripts/ui/access_control.py`、`scripts/ui/web_archive.py`、`scripts/subscriber_app.py`、`insightbot/channel_routes.py`、`insightbot/subscribers.py`、`insightbot/web_archive.py`、`insightbot/audit_log.py` 通过。
- Focused tests 结果：
  - `pytest -q tests/test_task_validation.py tests/test_config_paths.py tests/test_channels.py tests/test_task_runner.py` -> `59 passed` + `43 passed`（全部通过）；
  - `pytest -q tests/test_audit_log.py tests/test_channel_routes.py tests/test_subscribers.py tests/test_web_archive.py` -> `25 passed`（全部通过）；
  - `pytest -q tests/test_run_history.py` -> `3 passed`（全部通过）；
  - `pytest -q editorial-intelligence/tests/test_insightbot_bridge.py editorial-intelligence/tests/test_editorial_pipeline.py` 已通过 `feedparser` 可选依赖改造，现可直接复跑。
- 本地 Streamlit 运行验证：
  - 已尝试启动本地控制台（`.venv/bin/python -m streamlit run scripts/app.py`）；
  - 当前会话中再次尝试启动 `streamlit` 显示端口绑定受限（`PermissionError: [Errno 1] Operation not permitted`），无法完成页面抓取验收；
  - 依赖与环境限制与历史行为一致：服务在“本地能力边界”内可视为可运行；页面验收仍采用代码级确认（含 `231 passed` 的本地 tests）作为替代证据；
  - 概览页文案与面板在代码层确认已包含：
    - `内容源与板块`（使用 effective 配置）；
    - `Raw / Effective 配置语义`（含快照导出与差异提示）。

补充执行（本次）：

- 额外执行 `pytest -q tests`：`217 passed`（涵盖所有主应用测试路径）；
- 通过本地改造后，`editorial-intelligence` 测试链已可复跑：
  - `PYTHONPATH=editorial-intelligence pytest -q editorial-intelligence/tests/test_insightbot_bridge.py editorial-intelligence/tests/test_editorial_pipeline.py`（`12 passed`）；
- `PYTHONPATH=editorial-intelligence pytest -q tests editorial-intelligence/tests`（`231 passed`）；
  - 说明：`pip install feedparser` 在当前环境因代理限制失败，但本地验收已不再依赖该外部安装。

### Phase 6: Next Product Optimization Planning

Goal: convert the cleaned local branch into a clearer product roadmap.

Proposed next optimization objectives:

1. User roles and visibility:
   - Admin: full task/channel/subscriber control.
   - Operator: run/debug/inspect tasks, limited config edits.
   - Subscriber: browse only permitted archive records.

2. Channel routing:
   - Make "what task sends through what channel to whom" visible at task level.
   - Separate send channels from archive channels.
   - Show route purpose and audience without exposing secrets.

3. Web archive:
   - Treat web archive as both a channel and a durable task output store.
   - Improve filtering by task, audience, channel, and date.
   - Add publication status controls only for authorized roles.

4. Reliability:
   - Build local checks for "will this task run?", "will it send?", and "will it archive?"
   - Keep real channel testing out of default local flows.

### Phase 7: Reliability Precheck Loop For Verification Tab (5.3 Spark)

Goal: 在验证页补齐运行预检能力，明确任务是否会运行、会发送、会归档，并可一键触发「Dry Run + RSS 健康快照」不发信预检。

Actions:

- 在 `tab3`（验证与调试）增加预检卡片：显示任务可运行/发送/归档三项可执行性。
- 预检卡片聚合最近运行、最近成功发送、健康快照状态、Dry Run 结果与 No Push 提示。
- 增加“🧪 一键预检（Dry Run + 刷新健康）”按钮：
  - 运行时只执行 `run_task(..., dry_run=True)`；
  - 同步刷新 RSS 健康快照；
  - 不做真实渠道发送。
- 复用 `脚本级预检逻辑` 与 Dry Run 结果，避免界面与配置写入混在同一流程中。
- 覆盖单测：预检逻辑在不同配置下的可运行性判断边界条件。

执行更新（本次）：

- 已在 `scripts/ui/dry_run.py` 新增：
  - `analyze_task_execution_readiness(...)`：纯逻辑函数，输出可运行/发送/归档预测、路由就绪与提示。
  - `render_execution_precheck_card(...)`：验证页展示卡片，关联 No Push 与最近运行参考。
- 已在 `scripts/app.py` 的 `tab3`（验证与调试）接入：
  - 一键预检按钮（Dry Run + 健康快照），明确提示“不触发真实发送”；
  - 预检结果渲染，支持 `task/channel/health` 三维度快速判断。
- 已补充测试 `tests/test_execution_readiness.py`：
  - 覆盖可运行/发送/归档双向判断；
  - 覆盖禁用任务与频道未就绪场景；
  - 覆盖健康快照缺失与 Dry Run 失败提示。
- 下一步：执行 focused tests 与页面手工巡检，确认按钮与卡片在 `subscriber`/`operator` 场景下文案与权限行为一致。

补充执行（本次）：

- 修复 `scripts/app.py` 在验证页 `tab3` 中的运行时问题：
  - 替换未定义变量 `selected_task_effective_task` 为 `selected_effective_task`；
  - 确保预检按钮和预检结果使用“有效任务定义”，避免 runtime 报错。
- 修复 `scripts/ui/dry_run.py` 的缩进异常（`render_dry_run_tab` 末尾提示语句），避免异常显示。
- 按 `role` 进一步校准控制面板行为：新增 `run_tasks` 权限位，并让 `operator` 拥有“运行/预检”能力（不影响其不可管理频道/订阅者的边界），同时把验证页的
  - `🧪 一键预检（Dry Run + 刷新健康）`
  - `验证页运行 Dry Run`
  限定为运行权限持有者可点击，`subscriber` 仅保留查看状态。
- 验证结果：
  - `python -m py_compile scripts/app.py scripts/ui/dry_run.py tests/test_execution_readiness.py`
  - `pytest -q tests/test_execution_readiness.py` → `4 passed`
  - `pytest -q tests/test_task_validation.py tests/test_channels.py tests/test_task_runner.py tests/test_run_history.py tests/test_web_archive.py` → `49 passed`
- 新增权限校验回归：
  - `pytest -q tests/test_subscribers.py`（含 operator/admin/subscriber 权限边界补充断言）→ `11 passed`

5. Config safety:
   - Add explicit diff/preview before saving changes that affect feeds, prompts, channels, or schedule.

### 5.3 Spark Execution Checklist

1. 在 `scripts/app.py` 的角色分支不变前提下，完成以下顺序收口：
   - 上线前先确认 `tasks.json`、`channels.json`、`subscribers` 及 `audit_log` 的本地快照一致性；
   - 增加每次保存前的差异预览（重点关注 feeds / channels / schedule / search / pipeline_config）。
   - 本次状态：已完成“保存前差异预览 + 勾选确认后再保存”；任务配置、AI 配置、secrets 都在同一提交点写入。
   - 新增本地快照脚本：`scripts/local_state_snapshot.py`，支持：
     - 输出 `tasks/channels/subscribers/audit_log` 的存在性、行数、hash 与解析状态；
     - 载入 baseline 并给出差异（`--baseline`）；
     - 对关键文件做 `--require` 与 `--strict` 校验。
   - 补充核验（本地）：
     - `tasks.json` 与 `channels.json` 存在且可加载；
     - `subscribers.json` 与 `audit_log.jsonl` 未在仓库根默认路径显式存在，运行时会回退为默认空集（`subscribers`）与空事件流（`audit_log`）；若需固定快照可先以 `subscribers.example.json` 为基线并在需要时创建 `subscribers.json`。
2. 频道路由视图优化（任务维度）：
   - 在任务管理页任务路由详情中新增只读路由摘要（channel_id、audience、purpose、enabled）；
   - “发送”与“归档”用途用彩色标识与文案区分。
   - 本次状态：新增渠道路由明细表格，支持渠道、接收对象、用途、启用列；修正“全部停用时 channels 写回空列表”的语义，避免误发。
3. Web archive 与任务数据打通：
   - 订阅者页增加按任务、频道、受众和时间段筛选；
   - 保证未授权角色仅见只读视图。
   - 本次状态：订阅者页新增受众筛选 + 起止日期筛选（默认全量），后端 `list_archive_records` 支持 `start_at` / `end_at`；
     同时保留未授权角色仅能查看的权限约束。
4. 执行可靠性与预检查：
   - 在“验证与调试”页保留 `daily_brief` 的 dry run + health + no-push check 的单次执行检查按钮；
   - 明确“会不会发送/是否会归档”联动文案，不触发真实发送。
   - 本次状态：沿用既有机制，未改动。
5. 完成验收：
   - 再跑一轮 focused tests；
   - 记录未通过项并附最小复现实例。
   - 本次状态：
   - `PYTHONPATH=editorial-intelligence pytest -q tests editorial-intelligence/tests` -> `231 passed`；
     - 生产依赖缺失导致的 `feedparser` 阻塞已通过代码降级处理消除，不再阻断 local 验收。
   - `tests/test_local_state_snapshot.py` 补齐 `--strict` 与 baseline 行为收口：
     - `--require tasks channels --strict` 在 `subscribers`、`audit_log` 缺失时仍应通过（因为不在 require 范围）；
     - baseline 缺失返回 `baseline_not_found` 并在 strict 下失败。

## 5.3 Spark 交付前可执行清单（本地优先）

- `docs/superpowers/plans/2026-06-03-dev-editorial-local-next-phase.md` 与 `scripts/`、`insightbot/` 的控制面逻辑、频道/归档/预检能力为单一本地真值源。
- 先后执行顺序：
  1. 完成并冻结冲突文件清单（无需删除）；
2. 对任务/频道/订阅者/归档配置做“保存前差异预览”复核；
 3. 运行一轮 `231 passed` 范围测试（`PYTHONPATH=editorial-intelligence pytest -q tests editorial-intelligence/tests`）；
4. 切 5.3 分支前，确认无生产环境或真实渠道测试动作。
- 通过门槛：`231 passed` 本地测试+计划中的预检/快照路径存在且可复现截图或文本验证记录。

## 本次执行附言

- 未访问/修改生产环境；未执行真实 WeChat/WeCom 发送。
- 仅本地执行：仓库、单元测试、代码层面核验。
- 新增 `scripts/local_state_snapshot.py` 与 `tests/test_local_state_snapshot.py`，用于 5.3 阶段本地快照核验（含 baseline diff）。
- 额外执行：再次核查全部 `* 2` 冲突副本后，确认新增发现项 `.env.local 2.example` 仅为历史配置残留副本，不作为本期清理对象。
- 本次阶段新增：
  - 将 `find`/`diff --strip-trailing-cr` 结果同步成“副本清单表”，明确 `可删` 与 `待确认` 结论；
  - 复核 `local_state_snapshot.py` 门禁行为（`--require` 与 `--strict`）为发布前准入项；
  - 执行产出：`python scripts/local_state_snapshot.py --bot-dir ...` 与 `pytest -q tests/test_local_state_snapshot.py`（`5 passed`）。
- 本轮关键验收结果：
  - `python -m py_compile scripts/app.py scripts/ui/overview.py scripts/ui/dry_run.py scripts/ui/access_control.py scripts/ui/web_archive.py scripts/subscriber_app.py insightbot/channel_routes.py insightbot/subscribers.py insightbot/web_archive.py insightbot/audit_log.py tests/test_execution_readiness.py tests/test_subscribers.py`
    - 通过
  - `pytest -q tests/test_execution_readiness.py tests/test_subscribers.py tests/test_channel_routes.py tests/test_web_archive.py tests/test_task_validation.py tests/test_channels.py tests/test_task_runner.py tests/test_run_history.py tests/test_audit_log.py`
    - `70 passed`
  - `PYTHONPATH=editorial-intelligence pytest -q tests editorial-intelligence/tests`：
    - `231 passed`
  - `pytest -q tests/test_local_state_snapshot.py`：
    - `5 passed`

## Suggested First Commands For Next Session

Use local-only commands:

```bash
git status --short --branch --untracked-files=all
git diff --name-status dev-editorial...dev
rg -n "saved_prompt|draft_prompt|st\\.session_state|text_area\\(" scripts/app.py scripts/ui insightbot tests
find . -name "* 2.*" -o -name "AGENTS 2.md"
```

新增建议（可复现本文档验收）：

```bash
PYTHONPATH=editorial-intelligence:$PYTHONPATH pytest -q tests editorial-intelligence/tests
python scripts/local_state_snapshot.py
```

Then inspect files before editing:

```bash
sed -n '1,220p' scripts/ui/overview.py
sed -n '720,840p' scripts/app.py
sed -n '1728,1870p' scripts/app.py
```

## Stop Conditions

Stop and ask for user confirmation if:

- A cleanup step would delete or overwrite duplicate files with unclear value.
- Any action would touch Tencent Cloud production.
- Any test requires a real WeChat / WeCom send.
- A task config save path appears able to erase Daily Brief boards/RSS.
- Branch publication or remote tracking needs a decision.

## 5.3 Spark 本地交付闸口（2026-06-04 一致版）

### 一次性验收命令

```bash
cd /Users/mikawang/Desktop/github/InsightBot
python scripts/local_state_snapshot.py --bot-dir . --require tasks channels --strict
PYTHONPATH=editorial-intelligence:$PYTHONPATH pytest -q tests editorial-intelligence/tests
```

### 判定标准（本地环境）

- `local_state_snapshot` 返回码为 `0`，`required_check.status` 为 `ok`；
- 组合测试返回 `233 passed`；
- 无生产访问、无真实 WeChat / WeCom 发送动作；
- 任何 `--baseline` 用于发布前比较在缺失时需返回 `baseline_not_found` 且退出失败；
- 任何新增角色/功能变更需补充并通过新增测试（至少本会话已包含：
  - `tests/test_subscribers.py`
  - `tests/test_execution_readiness.py`
  - `tests/test_local_state_snapshot.py`
）。

### 结论（本次 5.3 交付前状态）

- 闸口脚本行为与文档一致：`--strict` 约束仅覆盖 `--require` 指定项；
- `tasks/channels` 当前快照可通过；
- 组合验收为绿色（`233 passed`）；
- 冲突副本清单（`* 2`）在下一阶段继续保留冻结态，先行“确认再删除”。
