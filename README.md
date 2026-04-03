## InsightBot (营销情报站)

一个"RSS + AI + 企业微信"的营销情报简报机器人：

- `smart_brief.py`: 抓取 RSS → 去重 → 调用 LLM 筛选/改写摘要 → 企业微信推送
- `app.py`: Streamlit 控制台（配置 feeds、提示词、定时任务、查看日志）
- `docker-compose.yml`: WeWe RSS + RSSHub + Redis（用于信源聚合）
- `insightbot/`: 核心 Python 包（discovery 信源发现、wecom 企业微信等模块）
- `scripts/`: 入口脚本
- `logs/`: 运行日志（每日轮转）

### Quick start (local)

1) 创建虚拟环境并安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> `-e .` 会同时安装运行时依赖和 `insightbot/` 包，无需单独跑 `pip install -r requirements.txt`。

2) 准备配置

```bash
cp .env.example .env
```

- 还需要一个 `config.json`（默认位置：`./config.json`，已在 `.gitignore` 中忽略）
- 可通过环境变量 `CONFIG_FILE` / `MARKETING_BOT_DIR` 指向其他路径

3) 启动信源服务（可选，但建议）

```bash
docker compose up -d
```

4) 启动控制台

```bash
streamlit run app.py
```

> 注意：需要从项目根目录运行（不是 `scripts/` 下），因为 Streamlit 默认在当前目录查找 `python-path`

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

1. 环境变量（`CONFIG_FILE`, `LOGS_DIR`, `LOG_FILE`, `BOT_LOG_FILE`, `MARKETING_BOT_DIR`）
2. 如果存在 `/root/marketing_bot` 则使用它
3. 否则使用当前仓库目录（脚本所在目录）

这样本地和服务器（`/root/marketing_bot`）都能跑同一套代码。

### Deploying to Tencent Cloud

```bash
# 1. SSH 到服务器
git clone <repo> /root/marketing_bot
cd /root/marketing_bot
git checkout main

# 2. 安装（会自动安装 insightbot 包）
pip install -e .

# 3. 配置 config.json（已有则跳过）

# 4. 安装 systemd 服务
sudo cp insightbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable insightbot
sudo systemctl start insightbot
```

