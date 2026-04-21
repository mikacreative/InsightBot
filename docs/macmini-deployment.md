# Mac Mini 本地部署指南

## 环境要求

- macOS（Apple Silicon 或 Intel）
- Docker Desktop（用于 Redis）
- Python 3.11+

## 快速启动

```bash
# 1. 复制环境配置
cp .env.local .env
# 编辑 .env，填写 WECOM_CID / WECOM_SECRET / WECOM_AID / AI_API_KEY 等

# 2. 安装 Python 依赖（本地开发模式）
pip install -r requirements.txt

# 3. 启动 Redis（Docker）
docker-compose up -d redis

# 4. 手动测试任务
python -m insightbot.cli --dry-run --task-id daily_brief
```

## 目录结构

```
~/Library/Application Support/InsightBot/   # 默认 bot_dir
├── tasks.json        # 任务定义
├── channels.json     # 频道配置
├── config.json        # 主配置（已废弃，迁移到 tasks.json）
└── logs/
    ├── bot.log
    └── daily_brief/
```

## RSSHub 独立部署

RSSHub 不在 docker-compose 里，需要单独部署：

```bash
# 方式1: Docker 直接跑（推荐）
docker run -d \
  --name rsshub \
  -p 1200:1200 \
  -e NODE_ENV=production \
  -e CACHE_TYPE=redis \
  -e REDIS_URL=redis://your-machine-ip:6379/ \
  diygod/rsshub

# 方式2: 直接安装（需要 Node.js）
git clone https://github.com/DIYgod/RSSHub.git /opt/rsshub
cd /opt/rsshub
npm install
NODE_ENV=production RSSHUB_CACHE_TYPE=redis RSSHUB_REDIS_URL=redis://localhost:6379/ npm start &
```

RSSHub 启动后，在 `tasks.json` 的 `source_strategy.primary_sources` 中填入 RSSHub 格式的 URL，例如：
```
https://rsshub.example.com:1200/weibo/user/123456789
```

## 企业微信接入

### 方式 A: Outbound Webhook（现有方式）
在 `tasks.json` 的 `channels` 中配置 WeCom 凭证，走 HTTPS API 发送。

### 方式 B: WebSocket 机器人（规划中）
参考 `wecom.py` 的 channel 协议，注册企业微信应用时开启「接收消息」模式，获取 `WECOM_AES_KEY` 和 `WECOM_TOKEN`，通过 WebSocket 长连接接收用户消息并回复。

## 开机自启（macOS launchd）

创建 `~/Library/LaunchAgents/com.insightbot.scheduler.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.insightbot.scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>insightbot.scheduler</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/InsightBot</string>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>/path/to/InsightBot/logs/launchd.log</string>
    <key>StandardErrorPath</key><string>/path/to/InsightBot/logs/launchd.log</string>
</dict>
</plist>
```

加载：`launchctl load ~/Library/LaunchAgents/com.insightbot.scheduler.plist`
