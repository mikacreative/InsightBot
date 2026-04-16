## InsightBot (营销情报站)

> 当前版本：`v2.0.0`

一个"RSS + AI + 企业微信"的多任务营销情报简报机器人：

- **多任务**：每个任务有独立的 RSS 源、Pipeline、频道和调度时间
- **多频道**：Channels 抽象层，支持企业微信等多样化推送渠道
- **内置调度器**：Python 线程循环，无需外部 cron
- **调试友好**：控制台 Dry Run 永远不发送真实消息，仅在面板展示结果

### 核心模块

| 模块 | 说明 |
|------|------|
| `insightbot/channels.py` | Channel 抽象层（WeChatChannel、ChannelRegistry） |
| `insightbot/scheduler.py` | 内置调度器（小时/分钟调度 + 70s 幂等保护） |
| `insightbot/task_runner.py` | 任务执行引擎（dry_run / 真实发送） |
| `insightbot/migrate.py` | v1 → v2 自动迁移 |
| `insightbot/editorial_pipeline.py` | Editorial Pipeline（默认主流程） |
| `insightbot/smart_brief_runner.py` | 经典简报流程 |
| `scripts/app.py` | Streamlit 管理台（9 个标签页） |

### v2.0 新能力

- **多任务多频道**：每个任务独立配置 feeds、pipeline、channels、schedule
- **Channels 抽象**：企业微信凭证单独存储在 `channels.json`
- **内置调度器**：无需外部 cron，支持"运行所有已启用任务"
- **调试控制台（tab8）**：Dry Run 在面板内展示完整简报预览 + 中间结果，零频道发送
- **自动迁移**：首次启动 v2.0 自动从 v1 配置生成 `channels.json` + `tasks.json`

### 管理台标签页

| Tab | 名称 | 说明 |
|-----|------|------|
| tab0 | 🏠 概览 | 运营总览、异常摘要、最近调试动态 |
| tab1 | 📋 任务管理 | 任务 CRUD、调度时间、频道分配 |
| tab2 | 📡 Channels | 频道 CRUD + 联通性测试 |
| tab3 | 🧠 AI 提示词调优 | Prompt Debug Console |
| tab4 | 🩺 RSS 健康度 | 单源级健康检查 |
| tab5 | 📝 运行日志 | 任务运行日志 |
| tab6 | 🔍 信源发现 | RSS 源探索 |
| tab7 | ⚙️ 推送版式定制 | 早报标题、无更新提示语、底部链接 |
| tab8 | 🔬 任务调试 | Dry Run 面板（零频道发送） |

### 数据模型

**`channels.json`** — 频道凭证（可配置多个企业微信）
```json
{
  "channels": {
    "wecom_main": {
      "type": "wecom",
      "name": "主频道",
      "cid": "...",
      "secret": "...",
      "agent_id": "..."
    }
  }
}
```

**`tasks.json`** — 任务定义（替代原来的内联配置）
```json
{
  "tasks": {
    "daily_brief": {
      "name": "每日营销早报",
      "enabled": true,
      "pipeline": "editorial",
      "feeds": { "💡 营销行业": { "rss": [...], "keywords": [], "prompt": "" } },
      "pipeline_config": {},
      "channels": ["wecom_main"],
      "schedule": { "hour": 8, "minute": 0 }
    }
  }
}
```

### 快速启动

1) 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ./insightbot        # 将 insightbot 包安装为可编辑模式
```

2) 准备配置

```bash
cp config.secrets.example.json config.secrets.json
# 编辑 config.secrets.json 填写企业微信和 AI 凭证
```

3) 启动（首次自动迁移）

```bash
streamlit run scripts/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

或命令行模式：

```bash
python -m insightbot.cli
```

### CLI 用法

```bash
# 启动调度循环（阻塞）
python -m insightbot.cli

# 运行指定任务（立即执行）
python -m insightbot.cli --task daily_brief

# Dry Run（仅面板展示，不发频道消息）
python -m insightbot.cli --task daily_brief --dry-run
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `MARKETING_BOT_DIR` | 工作目录，默认 `/root/marketing_bot` 或当前目录 |
| `CONFIG_CONTENT_FILE` | 覆盖 config.content.json 路径 |
| `CONFIG_SECRETS_FILE` | 覆盖 config.secrets.json 路径 |
| `CHANNELS_FILE` | 覆盖 channels.json 路径 |
| `TASKS_FILE` | 覆盖 tasks.json 路径 |
| `INSIGHTBOT_DRY_RUN` | 测试模式，频道发送不真实投递 |
| `AI_API_KEY` / `AI_API_URL` / `AI_MODEL` | 覆盖配置文件中的 AI 设置 |

### 日志

- 各 pipeline 日志写入 `./logs/bot.log`（每日轮转）

### 文档

- [Editorial Pipeline 设计文档](./docs/editorial_pipeline_design.md)
- [Search 集成设计文档](./docs/search_integration_design.md)
- [v2.0 架构变更说明](./docs/v2.0_architecture.md)
- [本地测试指南](./LOCAL_TESTING_GUIDE.md)
- [部署指南](./DEPLOYMENT_GUIDE.md)
