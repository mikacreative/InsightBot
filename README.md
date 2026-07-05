## InsightBot (营销情报站)

> 当前版本：`v0.4.0`
>
> 当前发布基线：
> - 控制台已收成 7 个主标签页
> - `editorial-intelligence` 路径已修复 task-level search query 执行
> - 任务模型主入口已切到 `sources + sections + pipeline_config`

一个 "RSS + AI + 多频道推送" 的多任务营销情报简报机器人。

- **多任务**：每个任务有独立的 RSS 源、Pipeline、频道和调度时间
- **多频道**：Channels 抽象层，支持企业微信、飞书应用、飞书机器人等多样化推送渠道
- **精细路由**：任务可声明“通过哪个频道、面向谁、用于什么场景”
- **订阅者页面**：`web_archive` 虚拟频道会把任务资讯沉淀为可在线浏览和回溯的 Web 存档
- **内置调度器**：前台阻塞循环，只需守护一个进程，无需外部 cron
- **任务中心控制台**：管理台按“当前任务”组织内容源、搜索补充、诊断、日志与 Dry Run
- **调试友好**：控制台 Dry Run 永远不发送真实消息，仅在面板展示结果
- **编辑式执行核**：`editorial pipeline` 已是默认主流程，底层正朝 `editorial-intelligence` skill runtime 过渡

### 核心模块

| 模块 | 说明 |
|------|------|
| `insightbot/channels.py` | Channel 抽象层（WeChatChannel、ChannelRegistry） |
| `insightbot/channel_routes.py` | 任务频道路由归一化，兼容旧列表与新对象格式 |
| `insightbot/web_archive.py` | Web 存档 JSONL 读写与记录回溯 |
| `insightbot/subscribers.py` | 订阅者、运营者、管理员 token 与权限矩阵 |
| `insightbot/audit_log.py` | 发布与权限变更审计日志 |
| `insightbot/scheduler.py` | 内置调度器（小时/分钟调度 + 70s 幂等保护） |
| `insightbot/task_runner.py` | 任务执行引擎（dry_run / 真实发送） |
| `insightbot/migrate.py` | v1 → v2 自动迁移 |
| `insightbot/editorial_pipeline.py` | Editorial Pipeline（默认主流程） |
| `insightbot/smart_brief_runner.py` | 经典简报流程 |
| `scripts/app.py` | Streamlit 管理台 |
| `scripts/subscriber_app.py` | 面向订阅者的只读 Web 存档页面 |

### v0.4.0 新能力

- **多任务多频道**：每个任务独立配置 feeds、pipeline、channels、schedule
- **Channels 抽象**：企业微信凭证单独存储在 `channels.json`
- **频道路由**：`tasks.json` 的 `channels` 既支持旧字符串列表，也支持带 audience/purpose 的对象列表
- **Web Archive**：新增 `web_archive` 虚拟频道，任务发送到该频道时写入 `data/web_archive.jsonl`
- **角色分层**：`subscriber` 只看内容，`operator` 可管理发布状态，`admin` 可管理任务、Channels 与权限
- **内置调度器**：无需外部 cron，直接守护 `python -m insightbot.cli` 即可
- **调试控制台（tab8）**：Dry Run 在面板内展示完整简报预览 + 中间结果，零频道发送
- **自动迁移**：首次启动会自动从旧版单任务配置生成 `channels.json` + `tasks.json`

### 当前发送策略

- `wecom`：发送前按 UTF-8 字节预算自动分片，避免中文 Markdown 在企业微信侧被截断
- `feishu_app`：优先走 `interactive` 卡片；超长内容会拆成多张连续卡片
- `feishu_bot`：保持轻量文本 fallback，适合作为兜底通知渠道

### 管理台标签页（当前）

| Tab | 名称 | 说明 |
|-----|------|------|
| tab0 | 🏠 概览 | 当前任务运营总览、异常摘要、最近调试动态 |
| tab1 | 📋 任务管理 | 当前任务的 feeds、搜索补充、pipeline、频道、调度 |
| tab2 | 📡 Channels | 频道 CRUD + 联通性测试 |
| tab3 | 🧪 验证与调试 | 最近运行、健康检查、Prompt Debug 与 No Push Diagnosis |
| tab4 | 📝 运行日志 | 当前任务优先的运行日志追踪 |
| tab5 | ⚙️ 推送版式定制 | 早报标题、无更新提示语、底部链接 |
| tab6 | 🔬 任务调试 | 任务级 Dry Run 面板（零频道发送） |
| tab7 | 🌐 订阅者页面 | Web Archive 历史资讯浏览与回溯 |
| tab8 | 👥 权限 | 管理 token、角色和 audience |

### 数据模型

运行态配置文件默认放在项目根目录，但这些文件是环境相关的本机状态，不再作为 Git 交付物提交。安全样例统一放在 [`config/examples/`](./config/examples/)。

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
    },
    "feishu_bot_fallback": {
      "type": "feishu_bot",
      "name": "飞书机器人兜底",
      "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
      "mention_all": false
    },
    "subscriber_page": {
      "type": "web_archive",
      "name": "订阅者页面",
      "public_name": "InsightBot Briefing"
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
| `web_archive` | 虚拟频道，不外发消息；将任务结果存入 Web 存档供订阅者浏览和回溯 | 推荐用于订阅页 |

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
      "sources": {
        "rss": [{ "id": "marketing_feed", "url": "https://example.com/feed.xml", "enabled": true }],
        "search": { "enabled": true, "provider": "baidu", "queries": [{ "keywords": "AI 营销", "section_hints": ["🤖 数智前沿"], "max_results": 10 }] }
      },
      "sections": {
        "💡 营销行业": { "prompt": "...", "keywords": ["营销"], "source_hints": ["marketing"] }
      },
      "pipeline_config": {},
      "channels": [
        "wecom_main",
        {
          "channel_id": "subscriber_page",
          "audience": "订阅者",
          "purpose": "archive"
        }
      ],
      "schedule": { "hour": 8, "minute": 0 }
    }
  }
}
```

`channels` 仍兼容旧格式 `["wecom_main"]`。当需要精细控制“什么任务通过什么渠道发送给谁”时，使用对象格式：

```json
{
  "channel_id": "feishu_exec",
  "audience": "管理层",
  "purpose": "summary",
  "enabled": true
}
```

### 订阅者页面与 Web 存档

- 管理台的 `🌐 订阅者页面` 标签可用于运营侧检查历史资讯。
- 管理台里可以把存档设为 `published`、`draft` 或 `unpublished`，并调整 `public` / `audience` 可见性。
- 面向订阅者时，推荐单独启动只读页面：

```bash
streamlit run scripts/subscriber_app.py \
  --server.address 0.0.0.0 \
  --server.port 8502
```

- 默认存档位置是 `data/web_archive.jsonl`，可用 `WEB_ARCHIVE_FILE` 覆盖。
- 每条存档都有 `record_id`，可以用 `?record_id=<id>` 直接定位某次任务结果。
- 订阅者访问范围由 `subscribers.json` 控制；只读页面用 `?token=<subscriber-token>` 解析订阅者受众组。

**`subscribers.json`** — 订阅者 token 与受众组

```json
{
  "subscribers": {
    "demo-admin-token": {
      "name": "管理员",
      "role": "admin",
      "audiences": ["management", "paid_subscribers", "public"]
    },
    "demo-operator-token": {
      "name": "运营者",
      "role": "operator",
      "audiences": ["management", "paid_subscribers", "public"]
    },
    "demo-management-token": {
      "name": "管理层读者",
      "role": "subscriber",
      "audiences": ["management", "public"]
    }
  }
}
```

没有 token 或 token 无效时，只能访问 `public` 范围。

控制台也支持 `?token=<token>`。生产环境建议设置 `INSIGHTBOT_CONSOLE_AUTH_REQUIRED=1`，这样无 token 不能进入管理员能力；本地默认可作为 Local Admin 进入，方便调试。通过权限页新增 token 时会保存 `token_hash`，避免继续把新 token 明文写入配置。

任务、Channels、发布状态和权限变更会写入 `data/audit_log.jsonl`，可用 `AUDIT_LOG_FILE` 覆盖；审计日志会自动脱敏 `secret`、`app_secret`、`api_key`、`webhook_url`、`token` 等字段。

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
cp config/examples/config.content.example.json config.content.json
cp config/examples/config.secrets.example.json config.secrets.json
cp config/examples/channels.example.json channels.json
cp config/examples/tasks.example.json tasks.json
```

然后在控制台 `📡 Channels` 页面检查并填写频道：

- `wecom`：`cid` / `secret` / `agent_id`
- `feishu_app`：`app_id` / `app_secret` / `receive_id` / `receive_id_type`
- `feishu_bot`：`webhook_url`
- `web_archive`：无需外部凭证，只需设置页面显示名称

> 生产环境的 `tasks.json` / `channels.json` / `config.content.json` / `config.secrets.json` 应视为 runtime 配置。部署前先备份生产配置，再更新代码，不要用本地样例覆盖生产文件。

3. 启动

```bash
PYTHONPATH=. streamlit run scripts/app.py \
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
| `WEB_ARCHIVE_FILE` | 覆盖 Web 存档 JSONL 路径 |
| `SUBSCRIBERS_FILE` | 覆盖 subscribers.json 路径 |
| `AUDIT_LOG_FILE` | 覆盖审计日志 JSONL 路径 |
| `INSIGHTBOT_CONSOLE_AUTH_REQUIRED` | 设为 `1` 时，控制台必须通过 token 获取管理权限 |
| `INSIGHTBOT_DRY_RUN` | 测试模式，频道发送不真实投递 |
| `AI_API_KEY` / `AI_API_URL` / `AI_MODEL` | 覆盖 AI 设置 |

### Channels 页行为

- 支持保存前联通性测试，测试使用的是**当前表单值**
- 显示当前频道配置是否完整
- 显示该频道当前被哪些任务引用
- 已被任务引用的频道不能直接删除

### 部署建议

- 生产环境推荐把 `python -m insightbot` 作为唯一常驻进程来守护
- 不建议同时维护系统 `cron`，否则容易与应用内调度重复触发
- 优先使用 `systemd`、`supervisord` 或容器自动重启策略来保证进程存活
- 如果需要从企业微信回调触发任务，可额外守护 `python -m insightbot --webhook`

### 文档

- [Runtime Config Inventory](./docs/runtime_config_inventory.md)
- [Editorial Pipeline 设计文档](./docs/editorial_pipeline_design.md)
- [Search 集成设计文档](./docs/search_integration_design.md)
- [多任务架构说明](./docs/v2.0_architecture.md)
- [Task Schema 重构：从 feeds 到 sources + sections](./docs/task_schema_sources_sections.md)
- [本地测试指南](./LOCAL_TESTING_GUIDE.md)
- [部署指南](./DEPLOYMENT_GUIDE.md)
