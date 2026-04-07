# Tencent Cloud 生产机迁移清单

目标：将生产环境从旧版单文件 `config.json` 迁移到新版双层配置：

- `config.content.json`：可纳入 Git，保存 feeds、settings、prompt、非敏感 AI 配置
- `config.secrets.json`：本机保留，不入 Git，保存企业微信凭证和 AI Key

适用分支：`dev`

## 1. 拉取最新代码

```bash
cd /root/marketing_bot
git pull origin dev
```

如果你的生产目录不是 `/root/marketing_bot`，替换成实际路径即可。

## 2. 准备内容配置

新版仓库已经自带一份接近生产环境的内容配置：

```bash
ls /root/marketing_bot/config.content.json
```

如果需要保留服务器上的旧配置做备份：

```bash
cp /root/marketing_bot/config.json /root/marketing_bot/config.json.bak.$(date +%Y%m%d-%H%M%S)
```

如果你想直接把服务器上的旧配置自动拆成新版双层配置，也可以运行：

```bash
cd /root/marketing_bot
python3 scripts/split_config.py \
  --input /root/marketing_bot/config.json \
  --content-out /root/marketing_bot/config.content.json \
  --secrets-out /root/marketing_bot/config.secrets.json
```

这个脚本会：

- 把 `wecom` 和 `ai.api_key` 拆到 `config.secrets.json`
- 把 `ai.api_url` / `ai.model` 改成环境变量占位
- 尽量保留旧配置里的其他内容结构

## 3. 生成 secrets 文件

先复制模板：

```bash
cp /root/marketing_bot/config.secrets.example.json /root/marketing_bot/config.secrets.json
```

编辑 `/root/marketing_bot/config.secrets.json`，填入：

```json
{
  "wecom": {
    "cid": "你的企业微信 corp id",
    "secret": "你的企业微信应用 secret",
    "aid": "你的企业微信 agent id"
  },
  "ai": {
    "api_key": "你的 AI API Key"
  }
}
```

## 4. 配置环境变量

推荐在生产机的 `.env`、`systemd` 或 shell profile 中设置：

```bash
export MARKETING_BOT_DIR=/root/marketing_bot
export CONFIG_CONTENT_FILE=/root/marketing_bot/config.content.json
export CONFIG_SECRETS_FILE=/root/marketing_bot/config.secrets.json

export AI_API_URL="你的 AI 接口 URL"
export AI_MODEL="你的模型名"
```

如果你的定时任务或服务已经固定在 `/root/marketing_bot` 下运行，`MARKETING_BOT_DIR` 也可以省略，但显式设置更稳。

## 5. 验证配置加载

先做一次最小验证：

```bash
cd /root/marketing_bot
python3 - <<'PY'
from insightbot.config import load_runtime_config
cfg = load_runtime_config("/root/marketing_bot")
print("feeds:", list(cfg.get("feeds", {}).keys()))
print("ai_model:", cfg.get("ai", {}).get("model"))
print("ai_url:", cfg.get("ai", {}).get("api_url"))
print("has_ai_key:", bool(cfg.get("ai", {}).get("api_key")))
print("has_wecom:", bool(cfg.get("wecom", {}).get("cid")))
PY
```

预期：

- `feeds` 能打印出三个板块
- `ai_model` / `ai_url` 能显示环境变量值
- `has_ai_key` / `has_wecom` 都应为 `True`

## 6. 手动跑一次任务

```bash
cd /root/marketing_bot
python3 smart_brief.py
```

观察：

- 控制台输出无报错
- `logs/bot.log` 有新日志
- 企业微信收到消息，或至少日志里能看到各板块被正常处理

## 7. 验证控制台写入行为

启动控制台：

```bash
cd /root/marketing_bot
streamlit run app.py
```

确认以下行为：

- 调整 prompt / feeds 后，修改的是 `config.content.json`
- `config.secrets.json` 不会被控制台覆盖
- AI tab 中不再直接编辑 API Key

## 8. 迁移完成后建议

- 保留旧 `config.json` 备份 1 到 2 周，再决定是否删除
- 轮换曾经出现在文件流转中的企业微信凭证和 AI API Key
- 后续所有 prompt 和信源改动都通过 Git 管理，不再直接改 secrets 文件

## 9. 常见问题

### 运行时报找不到配置文件

优先检查：

```bash
echo $CONFIG_CONTENT_FILE
echo $CONFIG_SECRETS_FILE
ls -l /root/marketing_bot/config.content.json
ls -l /root/marketing_bot/config.secrets.json
```

### 控制台改完后没生效

确认运行任务时使用的是同一个部署目录，并且定时任务里没有写死旧的 `CONFIG_FILE`。

### AI Key 正常但仍无推送

这通常不是配置加载问题，而是：

- RSS 当天确实没有足够内容
- prompt 过严
- 某板块的 RSS 源和 prompt 目标不匹配

此时优先检查 `logs/bot.log` 里是否出现：

- `AI 判定 ... 无合格内容`
- `RSS源 ... 抓取完成，共获得 0 条有效资讯`
