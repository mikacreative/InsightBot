# InsightBot 部署指南

**更新日期**：2026-04-16（适配 v2.0）

---

## 发布前检查清单

*   `README.md`、`pyproject.toml` 与包内版本号一致。
*   本地执行 `pytest tests/ -q` 全量通过（130+ 测试）。
*   关键配置采用 `config.content.json` + `config.secrets.json` 或环境变量。
*   在目标运行环境完成一次真实链路验证：
    *   控制台能正常打开（tab1 任务管理、tab2 Channels、tab8 任务调试）
    *   RSS 健康度面板能读取或刷新
    *   `python -m insightbot.cli --task daily_brief --dry-run` 能完整跑通
    *   频道联通性测试（tab2）在控制台正常
    *   真实推送或 `INSIGHTBOT_DRY_RUN=1` 输出符合预期

---

## 一、将 `dev` 分支合并到 `main`

### 1. 前提条件

*   已安装 Git 并配置好 GitHub 访问权限。
*   本地 `InsightBot` 项目目录已与 GitHub 仓库关联。
*   所有本地修改已提交或暂存。

### 2. 合并步骤

```bash
# 1. 切换到 main 分支并拉取最新
git checkout main && git pull origin main

# 2. 合并 dev 分支
git merge dev

# 3. 如有冲突，解决后：
git add .
git commit

# 4. 推送到远程
git push origin main
```

### 3. 最佳实践

*   **代码审查**：合并到 `main` 前进行代码审查。
*   **自动化测试**：确保 `pytest` 全量通过后再合并。
*   **小步快跑**：保持提交粒度较小，合并时更容易解决冲突。

---

## 二、腾讯云 CVM 部署

### 1. 前提条件

*   已通过 SSH 连接到腾讯云 CVM 实例。
*   CVM 上已安装 Git、Python 3.10+ 和 `pip`。
*   `docker` 和 `docker-compose` 已安装（如使用 Docker 部署）。

### 2. 部署步骤

```bash
# 1. 进入项目目录
cd /root/marketing_bot

# 2. 拉取最新 main 分支代码
git pull origin main

# 3. 安装或更新 Python 依赖
pip install -r requirements.txt

# 4. 确保 .env 包含最新配置（AI API Key、企业微信凭证等）
#    编辑 /root/marketing_bot/.env 或在腾讯云控制台配置环境变量

# 5. 首次部署会自动迁移（channels.json + tasks.json）
#    如需手动迁移：python -m insightbot.migrate

# 6. 启动服务（见下方服务管理方式）
```

### 3. 服务管理方式

**方式 A：systemd 常驻进程（推荐）**

> v2.0 之后，推荐只守护 `python -m insightbot.cli` 这个进程。
> 不需要再额外维护系统 `cron`，否则会和内置调度器形成双重触发。

```ini
# /etc/systemd/system/insightbot-scheduler.service
[Unit]
Description=InsightBot Scheduler

[Service]
Type=simple
User=root
WorkingDirectory=/root/marketing_bot
EnvironmentFile=/root/marketing_bot/.env
ExecStart=/root/marketing_bot/.venv/bin/python -m insightbot.cli
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable insightbot-scheduler
systemctl start insightbot-scheduler
systemctl status insightbot-scheduler
```

**方式 B：直接后台运行**

```bash
pkill -f insightbot  # 停止旧进程
nohup python3 -m insightbot.cli >> insightbot.log 2>&1 &
```

**方式 C：Docker Compose 部署**

```bash
docker-compose down
docker-compose up -d
```

### 4. 环境变量管理

*   **推荐**：将敏感信息作为腾讯云 CVM 的环境变量配置，不写入代码。
*   v2.0 新增 `CHANNELS_FILE` / `TASKS_FILE` 路径变量，生产环境建议显式指定：
  ```bash
  CHANNELS_FILE=/root/marketing_bot/channels.json
  TASKS_FILE=/root/marketing_bot/tasks.json
  MARKETING_BOT_DIR=/root/marketing_bot
  ```

### 5. 验证部署

```bash
# Dry Run 验证（不发送真实消息）
python -m insightbot.cli --task daily_brief --dry-run

# 生产运行模型
# 由 systemd 持续守护 python -m insightbot.cli
# 不再单独配置 cron

# 查看日志
journalctl -u insightbot-scheduler -f
# 或
tail -f /root/marketing_bot/logs/bot.log
```

---

## 三、腾讯云云函数 (SCF) 部署

### 1. 前提条件

*   已安装腾讯云 CLI 工具或使用腾讯云控制台。
*   `requirements.txt` 中所有依赖可在 SCF 环境中安装。

### 2. 部署步骤

1. **打包代码**：将项目打包成 ZIP 文件。
2. **创建/更新函数**：
    *   登录腾讯云 SCF 控制台。
    *   上传 ZIP 包。
    *   配置运行时环境 (Python 3.10+)。
    *   配置**环境变量**：`AI_API_KEY`, `AI_API_URL`, `AI_MODEL`, `WECOM_CID`, `MARKETING_BOT_DIR` 等。
    *   配置**触发器**：设置定时触发器（Cron 表达式），如每天 8:00 运行。
3. **测试**：在控制台进行测试，确保函数能正常执行。

---

## 四、监控与日志

*   **CVM + systemd**：日志输出到 `journalctl -u insightbot-scheduler`，结合 `logrotate` 轮转 `logs/bot.log`。
*   **CVM + Docker**：日志由 `docker-compose logs` 收集。
*   **SCF**：SCF 自动集成腾讯云日志服务 (CLS)，直接在控制台查看函数运行日志。

---

## 五、腾讯云安全组

确保入站规则开放：

| 端口 | 用途 |
|------|------|
| 8501 | Streamlit 管理台 |
| 22 | SSH |

---

> **重要提示**：在任何生产环境部署之前，务必进行充分的测试，并确保所有敏感信息已妥善管理，避免硬编码在代码中。
