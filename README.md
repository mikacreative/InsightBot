## InsightBot (营销情报站)

> 当前阶段版本：`v0.3.0`

一个“RSS + AI + 企业微信”的营销情报简报机器人：

- `smart_brief.py`: 抓取 RSS → 去重 → 调用 LLM 筛选/改写摘要 → 企业微信推送
- `app.py`: Streamlit 管理台（概览、信源健康、Prompt 调试、日志与诊断）
- `docker-compose.yml`: WeWe RSS + RSSHub + Redis（用于信源聚合）
- `scripts/`: 入口脚本（root 目录的 `app.py` 仍保留为兼容包装器）
- `logs/`: 运行日志（每日轮转）

### v0.3.0 已完成能力

这一阶段的重点不再只是“能跑”，而是让管理员能在控制台里更稳定地做日常运营判断。

- 拆分配置：`config.content.json` 可纳入 Git，`config.secrets.json` 与环境变量负责敏感信息
- Prompt Debug Console：
  - 草稿 Prompt 试跑
  - 当前版 vs 草稿版对比
  - 候选池预览
  - 最近 20 条调试记录留痕
- RSS 健康度面板：
  - 单源级状态检查
  - `正常 / 无更新 / 错误` 三态
  - 错误类型明细
  - 5 分钟缓存 + 手动刷新
- 无推送诊断：
  - 结合最近一次运行日志与 RSS 健康度
  - 区分“源异常 / 无候选 / Prompt 全拦截 / 运行异常”
- 概览页：
  - 最近一次任务摘要
  - 异常 RSS 源数
  - 今日候选总条数
  - 最近调试动态
  - 异常摘要卡片

如果你想看这一阶段的设计说明，可参考：

- [v0.3.0 管理台 PRD](./docs/v0.3.0_admin_console_prd.md)

### Quick start (local)

1) 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) 准备配置

- 推荐：复制并填写环境变量示例

```bash
cp .env.example .env
```

- 推荐使用拆分配置：

```bash
cp config.secrets.example.json config.secrets.json
```

- `config.content.json`：已纳入版本控制，保存 feeds、settings、system prompt 等内容规则
- `config.secrets.json`：已在 `.gitignore` 中忽略，保存企业微信凭证和 AI 运行时连接配置（`api_key` / `api_url` / `model`）
- 如果你仍在使用旧版单文件 `config.json`，当前版本仍兼容；也可以通过 `CONFIG_FILE` 指向旧路径

3) 启动信源服务（可选，但建议）

```bash
docker compose up -d
```

4) 启动控制台

```bash
streamlit run app.py
```

### Running the bot

```bash
python smart_brief.py
```

### Logs

- `smart_brief` 日志默认写入 `./logs/bot.log`（每日轮转，保留 30 天）
- cron 标准输出默认写入 `./logs/cron.log`
- `daily_brief.py` 日志默认写入 `./logs/daily_brief.log`（每日轮转）

### Path configuration (important)

代码默认会按以下顺序找配置/日志路径：

1. 显式指定的 `CONFIG_FILE`（旧版单文件）
2. 当前目录下的 `config.content.json` + `config.secrets.json`
3. 当前目录下的兼容旧版 `config.json`
4. 如果存在 `/root/marketing_bot` 则使用它；否则使用当前仓库目录

运行时环境变量（如 `AI_API_KEY`、`WECOM_SECRET`）会覆盖文件中的同名配置，便于生产环境做 secrets 注入。

这样本地和服务器（`/root/marketing_bot`）都能跑同一套代码。
