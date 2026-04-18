# Changelog

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
