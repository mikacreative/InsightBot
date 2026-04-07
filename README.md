## InsightBot (营销情报站)

一个“RSS + AI + 企业微信”的营销情报简报机器人：

- `smart_brief.py`: 抓取 RSS → 去重 → 调用 LLM 筛选/改写摘要 → 企业微信推送
- `app.py`: Streamlit 控制台（配置 feeds、提示词、定时任务、查看日志）
- `docker-compose.yml`: WeWe RSS + RSSHub + Redis（用于信源聚合）
- `scripts/`: 入口脚本（root 目录的 `app.py` 仍保留为兼容包装器）
- `logs/`: 运行日志（每日轮转）

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
