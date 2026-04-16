# Changelog

## v2.0.0 (2026-04-16)

### 管理台修正

- **任务中心控制台**：`scripts/app.py` 改为以“当前任务”为主视角，任务详情页可直接编辑 feeds、search、pipeline_config、channels、schedule
- **任务归属增强**：概览、No Push Diagnosis、运行日志、Dry Run 结果都补充当前任务上下文显示
- **任务级信源操作**：信源发现页新增的 RSS 会写回当前任务，不再误写全局旧配置
- **调度常驻模型修正**：`scheduler.run_loop()` 改为前台阻塞循环，部署时只需守护 `python -m insightbot.cli`

### 架构升级

- **多任务系统**：每个任务独立配置 feeds、pipeline、channels、schedule，不再共享单一 RSS 池
- **Channels 抽象层**：`channels.json` 独立存储企业微信凭证，支持多频道管理
- **内置调度器**：Python 线程循环替代外部 cron，支持"运行所有已启用任务"，70s 幂等保护
- **调试优先**：控制台 Dry Run 永远不发送真实消息，仅在面板展示结果
- **自动迁移**：首次启动 v2.0 自动从 v1 配置生成 `channels.json` + `tasks.json`

### 新增文件

- `insightbot/channels.py` — Channel 抽象（WeChatChannel、ChannelRegistry、send_to_channel、test_channel）
- `insightbot/scheduler.py` — Task / Scheduler 类，run_loop() daemon thread，run_task_by_id()，run_all_enabled()
- `insightbot/task_runner.py` — run_task() 统一入口，dry_run 逻辑，pipeline dispatch，channel dispatch
- `insightbot/migrate.py` — migrate_from_v1() 自动迁移
- `tests/test_scheduler.py` — 调度器单元测试
- `tests/test_channels.py` — Channel 抽象单元测试
- `tests/test_task_runner.py` — Task runner 单元测试
- `tests/test_migrate.py` — 迁移逻辑单元测试

### 修改文件

- `insightbot/paths.py` — 新增 `channels_file_path()` / `tasks_file_path()`
- `insightbot/config.py` — 新增 `load_channels` / `save_channels` / `load_tasks` / `save_tasks` / `load_tasks_config`
- `insightbot/editorial_pipeline.py` — 移除所有 `send_markdown_to_app` 调用，返回 `final_markdown`
- `insightbot/smart_brief_runner.py` — 同上，run_task() 改为返回 dict
- `insightbot/cli.py` — 重写，新增 `--task` / `--dry-run` 参数
- `insightbot/__init__.py` — `__version__ = "2.0.0"`
- `scripts/app.py` — 重构为 9 tab（新增 tab1 任务管理、tab2 Channels、tab8 任务调试）

### Bug Fixes

- **import 错误**：`load_channels` / `save_channels` 实际在 `config.py` 而非 `channels.py`
- **缺失导入**：`cron_log_file_path` / `load_tasks` / `save_tasks` 未导入导致运行时错误
- **sidebar 错误**：`load_channels(bot_dir)` 在调度器状态处应为 `load_tasks(bot_dir)`
- **入口缺失**：`main()` 定义后无 `if __name__ == "__main__"` 调用，导致空白页面

### 管理台变更

| 旧标签 | 新标签 | 说明 |
|--------|--------|------|
| — | tab1 📋 任务管理 | **新增**：任务 CRUD、调度、频道分配 |
| — | tab2 📡 Channels | **新增**：频道 CRUD + 联通性测试 |
| tab2 ⚙️ 推送版式定制 | tab7 ⚙️ 推送版式定制 | 位置迁移 |
| tab7 📡 Editorial Pipeline | tab8 🔬 任务调试 | 改为 Dry Run 调试界面 |

### 清理

- 删除废弃入口：`app.py`、`smart_brief.py`、`daily_brief.py`（v1 遗留）
- 删除废弃调试脚本：`debug_prompt.py`、`debug_rss_check.py`、`debug_run.py`
- 删除孤立文件：`insightbot/daily_brief_runner.py`、`insightbot/discovery_service.py`
- 删除根目录重复 `pyproject.toml`

---

## v0.3.1 (之前版本)

见历史提交记录。默认流程为 Editorial Pipeline 双阶段编辑流水线。
