## Signal Desk / InsightBot (营销情报站)

> 当前阶段：`Signal Desk product shell + Pattern contracts`

Signal Desk 是面向营销传播团队的动态情报工作台；InsightBot 是现有 RSS / search / AI pipeline / channels / scheduler 运行底座。

当前产品结构是两层：

- **Signal Desk**：默认用户工作台，只暴露 Rooms、Signals、Saved、Briefs，让用户提出情报需求、调用 pattern、查看和保存结果。
- **Control Center**：内部运营和质控中心，管理 tasks、channels、validation、logs、delivery format、debug 和 raw pipeline。
- **Pattern Library**：把 source pack、editorial policy、judgement lenses、quality gates 和用户 intent 收成可调用的产品能力。

运行底座仍保留：

- **多任务**：每个任务有独立的内容源、pipeline、频道和调度时间。
- **多频道**：Channels 抽象层，支持企业微信、飞书应用、飞书机器人等推送渠道。
- **内置调度器**：前台阻塞循环，只需守护一个进程，无需外部 cron。
- **调试友好**：Dry Run 永远不发送真实消息，仅在面板展示结果。

### 核心模块

| 模块 | 说明 |
|------|------|
| `insightbot/channels.py` | Channel 抽象层（WeChatChannel、ChannelRegistry） |
| `insightbot/scheduler.py` | 内置调度器（小时/分钟调度 + 70s 幂等保护） |
| `insightbot/task_runner.py` | 任务执行引擎（dry_run / 真实发送） |
| `insightbot/migrate.py` | v1 → v2 自动迁移 |
| `insightbot/editorial_pipeline.py` | Editorial Pipeline（默认主流程） |
| `insightbot/smart_brief_runner.py` | 经典简报流程 |
| `insightbot/signal_desk/patterns.py` | Pattern、Intent、Quality Gate 合同 |
| `insightbot/signal_desk/models.py` | BriefingRoom、SavedSignal、FeedbackRecord 数据模型 |
| `scripts/ui/signal_desk/product_shell.py` | Signal Desk / Control Center 产品壳 |
| `scripts/app.py` | Streamlit Web app 入口 |

### 当前新能力

- **用户工作台优先**：默认进入 `Signal Desk`，不让普通用户面对任务配置、channel 和验证细节。
- **Control Center 后置**：复杂配置仍保留，但作为内部 operator / admin surface。
- **Pattern contract**：首个内置 pattern 是 `Client Opportunity Radar`，包含 intent、默认 source、judgement lenses 和 quality gate。
- **反馈上下文**：反馈记录已带 `pattern_id` 和 room intent context，后续可用于 pattern tuning。
- **自动迁移与运行底座**：仍支持旧配置迁移、任务调度、channels 和 CLI 运行。

### 产品入口

| Product Mode | Tabs | 说明 |
| --- | --- | --- |
| `Signal Desk` | Rooms / Signals / Saved / Briefs | 面向使用者的情报工作台。创建 room、调用 pattern、看 signal、保存素材、准备 brief。 |
| `Control Center` | Overview / Signal Desk / Saved Signals / Task Management / Channels / Validation & Debug / Logs / Delivery Format / Task Debug | 面向内部运营和质控。管理 pipeline、任务、频道、验证、日志和调试。 |

长期方向是让 Agent 辅助 Pattern Library 和 Control Center，但 MVP 先保持 human-first，不把 autonomous agent 放进关键路径。

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

### Channels 页行为

- 频道支持保存前联通性测试，测试使用的是**当前表单值**
- 频道会显示当前配置是否完整，以及被哪些任务引用
- 已被任务引用的频道不能直接删除，避免破坏生产任务

### 部署建议

- 生产环境推荐把 `python -m insightbot.cli` 作为唯一常驻进程来守护
- 不建议同时维护系统 `cron`，否则容易与应用内调度重复触发
- 优先使用 `systemd`、`supervisord` 或容器自动重启策略来保证进程存活

### 文档

- [Signal Desk PRD](./docs/signal_desk_prd.md)
- [Signal Desk MVP Architecture](./docs/signal_desk_mvp_architecture.md)
- [Signal Desk Product IA And Pattern Architecture](./docs/signal_desk_product_ia_pattern_architecture.md)
- [Signal Desk MVP Implementation Plan](./docs/superpowers/plans/2026-05-04-signal-desk-mvp.md)
- [Signal Desk Product Shell And Pattern Contracts Plan](./docs/superpowers/plans/2026-05-04-signal-desk-product-shell-pattern-contracts.md)
- [Editorial Pipeline 设计文档](./docs/editorial_pipeline_design.md)
- [Search 集成设计文档](./docs/search_integration_design.md)
- [多任务架构说明](./docs/v2.0_architecture.md)
- [本地测试指南](./LOCAL_TESTING_GUIDE.md)
- [部署指南](./DEPLOYMENT_GUIDE.md)
