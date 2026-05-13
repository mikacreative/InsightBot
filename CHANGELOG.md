# Changelog

## Unreleased (2026-04-29)

### Runtime

- 修复 `editorial-intelligence` 路径下 task-level `search.queries` 的执行链：运行时会先把控制台保存的 query 规范化成真正可执行的字符串列表
- 为 `editorial-intelligence` 的搜索 adapter 补上 `baidu` provider，和当前腾讯云生产环境的默认搜索配置对齐
- 新增 `python -m insightbot` 统一入口，并支持 `--webhook` 启动企业微信回调服务

### Console

- 控制台当前基线收敛为 7 个主标签页
- 原 `AI 提示词调优` / `RSS 健康度` / `信源发现` 不再作为长期一级入口
- Prompt Debug 能力继续收口到 `验证与调试` 页内联工作流

### Schema And Docs

- `dev-editorial` 开发基线已把任务模型主入口切到 `sources + sections + pipeline_config`
- 明确当前不做 `feeds -> sources + sections` 的长期兼容层，后续按任务数量手动迁移
- 运行时内部仍临时派生 `feeds` 视图给 Prompt Debug / 健康检查 / 少量 legacy 路径使用
- `README` 与 `v2.0_architecture` 已同步当前控制台结构和下一阶段 schema 方向

## v0.4.0 (2026-04-18)

首次正式 release。

### Highlights

- 多任务、多频道的任务模型落地：`feeds`、`pipeline`、`channels`、`schedule` 都按任务独立配置
- `channels.json` + `tasks.json` 成为稳定运行时配置，首次启动支持自动迁移
- 内置调度器成为默认生产运行方式，不再依赖系统 `cron`
- Streamlit 控制台完成任务中心化，支持 Channels 管理、任务调试、健康检查与诊断
- Editorial Pipeline 具备全局候选池、初筛、栏目分配、栏目终筛的完整链路

### Channels

- 企业微信 `wecom` 渠道稳定可用
- 新增 `feishu_app`，通过飞书应用鉴权 + OpenAPI 发送，支持 `interactive` richer message 卡片
- 保留 `feishu_bot` 作为 webhook 兜底渠道
- Channels 页面新增：
  - 保存前联通性测试
  - 频道配置完整性校验
  - 当前任务引用展示
  - 引用保护，阻止删除仍被任务使用的频道

### Ops

- 腾讯云 CVM 生产部署路径已验证
- `systemd` 常驻 `insightbot-web.service` + `insightbot-scheduler.service`
- Dry Run 面板现在直接展示流程摘要和完整 `stage_results`

### Notes

- 历史上的 `v2.x`、`v2.1`、`v0.3.x` 叫法均为开发阶段内部命名，不代表正式 release 编号
- 从本次开始，正式版本按 `0.x.x` 维护
