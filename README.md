## InsightBot (营销情报站)

> 当前版本：`v0.4.0`
>
> 最新开发基线：
> - `dev-editorial` 已把控制台收成 7 个主标签页
> - `editorial-intelligence` 路径已修复 task-level search query 执行
> - 任务模型主入口已切到 `sources + sections + pipeline_config`

一个"RSS + AI + 多频道推送"的多任务营销情报简报机器人：

- **多任务**：每个任务有独立的 RSS 源、Pipeline、频道和调度时间
- **多频道**：Channels 抽象层，支持企业微信、飞书应用、飞书机器人等多样化推送渠道
- **内置调度器**：前台阻塞循环，只需守护一个进程，无需外部 cron
- **任务中心控制台**：管理台按“当前任务”组织内容源、搜索补充、诊断、日志与 Dry Run
- **调试友好**：控制台 Dry Run 永远不发送真实消息，仅在面板展示结果
- **编辑式执行核**：`editorial pipeline` 已是默认主流程，底层正朝 `editorial-intelligence` skill runtime 过渡

### 核心模块

| 模块 | 说明 |
|------|------|
| `insightbot/channels.py` | Channel 抽象层（WeChatChannel、ChannelRegistry） |
| `insightbot/scheduler.py` | 内置调度器（小时/分钟调度 + 70s 幂等保护） |
| `insightbot/task_runner.py` | 任务执行引擎（dry_run / 真实发送） |
| `insightbot/migrate.py` | v1 → v2 自动迁移 |
| `insightbot/editorial_pipeline.py` | Editorial Pipeline（默认主流程） |
| `insightbot/smart_brief_runner.py` | 经典简报流程 |
| `scripts/app.py` | Streamlit 管理台（当前为 7 个主标签页） |

### v0.4.0 新能力

- **多任务多频道**：每个任务独立配置 feeds、pipeline、channels、schedule
- **Channels 抽象**：企业微信凭证单独存储在 `channels.json`
- **内置调度器**：无需外部 cron，直接守护 `python -m insightbot` 即可
- **调试控制台**：Dry Run 在面板内展示完整简报预览 + 中间结果，零频道发送
- **自动迁移**：首次启动会自动从旧版单任务配置生成 `channels.json` + `tasks.json`

### 管理台标签页（当前）

| Tab | 名称 | 说明 |
|-----|------|------|
| tab0 | 🏠 概览 | 当前任务运营总览、异常摘要、最近调试动态 |
| tab1 | 📋 任务管理 | 当前任务的 feeds、搜索补充、pipeline、频道、调度 |
| tab2 | 📡 Channels | 频道 CRUD + 联通性测试 |
| tab3 | 🧪 验证与调试 | 健康检查、No Push Diagnosis、板块调试、日志摘要 |
| tab4 | 📝 运行日志 | 当前任务优先的运行日志追踪 |
| tab5 | ⚙️ 推送版式定制 | 早报标题、无更新提示语、底部链接 |
| tab6 | 🔬 任务调试 | 任务级 Dry Run 面板（零频道发送） |

> 说明：
> - 旧的 `AI 提示词调优` / `RSS 健康度` / `信源发现` 已不再作为一级标签页长期保留
> - Prompt Debug 能力正在合并到 `验证与调试`

### 数据模型

**`channels.json`** — 频道凭证（可配置多个企业微信 / 飞书通道）
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
      "receive_id": "oc_xxx / chat_xxx",
      "receive_id_type": "chat_id",
      "message_template": "interactive"
    },
    "feishu_bot_fallback": {
      "type": "feishu_bot",
      "name": "飞书机器人兜底",
      "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
      "mention_all": false
    }
  }
}
```

### 当前支持的频道类型

| 类型 | 用途 | 推荐程度 |
|------|------|------|
| `wecom` | 企业微信应用推送 | 推荐 |
| `feishu_app` | 飞书应用鉴权后通过 OpenAPI 发送，支持 richer message 卡片 | 推荐 |
| `feishu_bot` | 飞书群机器人 webhook，适合作为轻量 fallback | 可选 |

> 对飞书来说，**推荐默认接入 `feishu_app`**。  
> 它通过飞书应用鉴权后走官方消息 API，支持 `interactive` 卡片；`feishu_bot` 仍可用，但更适合作为 webhook 兜底通道。

**`tasks.json`** — 任务定义（当前主结构）
```json
{
  "tasks": {
    "daily_brief": {
      "name": "每日营销早报",
      "enabled": true,
      "pipeline": "editorial",
      "sources": {
        "rss": [{ "id": "marketing_feed", "url": "https://example.com/feed.xml", "enabled": true }],
        "search": { "enabled": true, "provider": "baidu", "queries": [{ "keywords": "AI 营销", "section_hints": ["🤖 数智前沿"], "max_results": 10 }] }
      },
      "sections": {
        "💡 营销行业": { "prompt": "...", "keywords": ["营销"], "source_hints": ["marketing"] }
      },
      "pipeline_config": {},
      "channels": ["wecom_main"],
      "schedule": { "hour": 8, "minute": 0 }
    }
  }
}
```

> 当前 `dev-editorial` 开发基线已经把任务模型主入口切到：
>
> - `sources`
> - `sections`
> - `pipeline_config`
>
> 运行时内部仍会临时派生一份 `feeds` 视图，用于兼容 Prompt Debug、健康检查和少量 legacy 路径；这层适配不是长期主模型。  
> 设计稿见：[Task Schema 重构：从 feeds 到 sources + sections](./docs/task_schema_sources_sections.md)

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

然后在控制台的 `📡 Channels` 页面创建并填写频道：

- `wecom`：`cid` / `secret` / `agent_id`
- `feishu_app`：`app_id` / `app_secret` / `receive_id` / `receive_id_type`
- `feishu_bot`：`webhook_url`

3) 启动（首次自动迁移）

```bash
streamlit run scripts/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

或命令行模式：

```bash
python -m insightbot
```

### CLI 用法

```bash
# 启动调度循环（阻塞）
python -m insightbot

# 运行指定任务（立即执行）
python -m insightbot --task daily_brief

# Dry Run（仅面板展示，不发频道消息）
python -m insightbot --task daily_brief --dry-run

# 启动企业微信回调服务（端口 8080）
python -m insightbot --webhook
```

> `python -m insightbot.cli` 仍可用，但推荐统一使用 `python -m insightbot`。

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

### Channels 页行为

- 频道支持保存前联通性测试，测试使用的是**当前表单值**
- 频道会显示当前配置是否完整，以及被哪些任务引用
- 已被任务引用的频道不能直接删除，避免破坏生产任务

### 部署建议

- 生产环境推荐把 `python -m insightbot` 作为唯一常驻进程来守护
- 不建议同时维护系统 `cron`，否则容易与应用内调度重复触发
- 优先使用 `systemd`、`supervisord` 或容器自动重启策略来保证进程存活
- 如果需要从企业微信回调触发任务，可额外守护 `python -m insightbot --webhook`

### 文档

- [Editorial Pipeline 设计文档](./docs/editorial_pipeline_design.md)
- [Search 集成设计文档](./docs/search_integration_design.md)
- [多任务架构说明](./docs/v2.0_architecture.md)
- [Task Schema 重构：从 feeds 到 sources + sections](./docs/task_schema_sources_sections.md)
- [本地测试指南](./LOCAL_TESTING_GUIDE.md)
- [部署指南](./DEPLOYMENT_GUIDE.md)
