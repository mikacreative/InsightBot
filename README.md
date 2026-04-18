## InsightBot (营销情报站)

> 当前版本：`v0.4.0`

一个 "RSS + AI + 多频道推送" 的多任务营销情报简报机器人。

- **多任务**：每个任务有独立的 RSS 源、Pipeline、频道和调度时间
- **多频道**：Channels 抽象层，支持企业微信、飞书应用、飞书机器人
- **内置调度器**：前台阻塞循环，只需守护一个进程，无需外部 cron
- **任务中心控制台**：按“当前任务”组织内容源、搜索补充、诊断、日志与 Dry Run
- **调试友好**：Dry Run 永远不发送真实消息，仅在面板展示结果

### 核心模块

| 模块 | 说明 |
|------|------|
| `insightbot/channels.py` | Channel 抽象层 |
| `insightbot/scheduler.py` | 内置调度器 |
| `insightbot/task_runner.py` | 任务执行引擎 |
| `insightbot/migrate.py` | 旧配置自动迁移 |
| `insightbot/editorial_pipeline.py` | Editorial Pipeline |
| `insightbot/smart_brief_runner.py` | 经典简报流程 |
| `scripts/app.py` | Streamlit 管理台 |

### 当前支持的频道类型

| 类型 | 用途 | 推荐程度 |
|------|------|------|
| `wecom` | 企业微信应用推送 | 推荐 |
| `feishu_app` | 飞书应用鉴权后通过 OpenAPI 发送，支持 interactive 卡片 | 推荐 |
| `feishu_bot` | 飞书群机器人 webhook，适合作为轻量 fallback | 可选 |

> 对飞书来说，默认推荐 `feishu_app`。  
> 它走飞书应用鉴权 + 官方消息 API，适合正式生产发送；`feishu_bot` 更适合作为 webhook 兜底。

### 配置模型

**`channels.json`**

```json
{
  "channels": {
    "wecom_main": {
      "type": "wecom",
      "name": "主频道",
      "cid": "...",
      "secret": "...",
      "agent_id": "..."
    },
    "feishu_app_main": {
      "type": "feishu_app",
      "name": "飞书应用频道",
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "receive_id": "chat_xxx",
      "receive_id_type": "chat_id",
      "message_template": "interactive"
    }
  }
}
```

**`tasks.json`**

```json
{
  "tasks": {
    "daily_brief": {
      "name": "每日营销早报",
      "enabled": true,
      "pipeline": "editorial",
      "feeds": {
        "💡 营销行业": {
          "rss": ["https://example.com/feed.xml"],
          "keywords": [],
          "prompt": ""
        }
      },
      "pipeline_config": {},
      "channels": ["wecom_main"],
      "schedule": { "hour": 8, "minute": 0 }
    }
  }
}
```

### 快速启动

1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ./insightbot
```

2. 准备配置

```bash
cp config.secrets.example.json config.secrets.json
```

然后在控制台 `📡 Channels` 页面创建并填写频道：

- `wecom`：`cid` / `secret` / `agent_id`
- `feishu_app`：`app_id` / `app_secret` / `receive_id` / `receive_id_type`
- `feishu_bot`：`webhook_url`

3. 启动

```bash
streamlit run scripts/app.py --server.address 0.0.0.0 --server.port 8501
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
| `CONFIG_CONTENT_FILE` | 覆盖 `config.content.json` 路径 |
| `CONFIG_SECRETS_FILE` | 覆盖 `config.secrets.json` 路径 |
| `CHANNELS_FILE` | 覆盖 `channels.json` 路径 |
| `TASKS_FILE` | 覆盖 `tasks.json` 路径 |
| `INSIGHTBOT_DRY_RUN` | 测试模式，频道发送不真实投递 |
| `AI_API_KEY` / `AI_API_URL` / `AI_MODEL` | 覆盖 AI 设置 |

### Channels 页行为

- 支持保存前联通性测试，测试使用的是**当前表单值**
- 显示当前频道配置是否完整
- 显示该频道当前被哪些任务引用
- 已被任务引用的频道不能直接删除

### 部署建议

- 生产环境推荐把 `python -m insightbot.cli` 作为唯一调度常驻进程
- 如需 UI，同时守护 `streamlit run scripts/app.py`
- 不建议再维护系统 `cron`，否则容易与应用内调度重复触发

### 文档

- [多任务架构说明](./docs/v2.0_architecture.md)
- [Editorial Pipeline 设计文档](./docs/editorial_pipeline_design.md)
- [Search 集成设计文档](./docs/search_integration_design.md)
- [本地测试指南](./LOCAL_TESTING_GUIDE.md)
- [部署指南](./DEPLOYMENT_GUIDE.md)
