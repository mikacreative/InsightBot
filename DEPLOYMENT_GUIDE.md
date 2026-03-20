# InsightBot 部署指南

本文档旨在指导如何将 `dev` 分支的最新代码合并到 `main` 分支，并将其部署到腾讯云环境。

## 一、将 `dev` 分支合并到 `main`

在将 `dev` 分分支的最新功能和修复合并到 `main` 分支之前，请确保所有 `dev` 分支上的测试都已通过，并且代码已准备好上线。此过程应在本地开发环境中执行。

### 1. 前提条件

*   已安装 Git 并配置好 GitHub 访问权限。
*   本地 `InsightBot` 项目目录已与 GitHub 仓库关联。
*   所有本地修改已提交或暂存。

### 2. 合并步骤

请在你的本地 `InsightBot` 项目目录下，按顺序执行以下 Git 命令：

```bash
# 1. 切换到 main 分支
git checkout main

# 2. 从远程仓库拉取最新的 main 分支代码，确保本地 main 是最新的
git pull origin main

# 3. 将 dev 分支合并到 main 分支
git merge dev

# 4. 如果存在合并冲突，请手动解决冲突。
#    解决冲突后，使用以下命令标记冲突已解决并完成合并：
#    git add .
#    git commit

# 5. 将合并后的 main 分支推送到 GitHub 远程仓库
git push origin main
```

### 3. 最佳实践

*   **代码审查 (Code Review)**：在合并到 `main` 之前，最好进行代码审查，确保代码质量和功能符合预期。
*   **自动化测试**：确保 `dev` 分支上的所有自动化测试（如 `pytest`）都已通过，以减少引入错误的风险。
*   **小步快跑**：尽量保持 `dev` 分支的提交粒度较小，这样在合并时更容易解决冲突。

## 二、腾讯云部署方案

鉴于你原先的 `main` 分支是从腾讯云直接 `push` 上去的，我们假设你有一个现有的腾讯云服务器 (CVM) 或云函数 (SCF) 环境，并且 `InsightBot` 已经在上面运行。这里提供两种常见的部署策略：

### 策略一：直接在腾讯云服务器上拉取最新代码 (CVM)

如果你在腾讯云上使用 CVM 运行 `InsightBot`，这是最直接的更新方式。

#### 1. 前提条件

*   已通过 SSH 连接到你的腾讯云 CVM 实例。
*   CVM 上已安装 Git、Python 3.10+ 和 `pip`。
*   `InsightBot` 项目目录已存在于 CVM 上，并且已配置好 Git 远程仓库。
*   CVM 上已安装 `docker` 和 `docker-compose` (如果使用 Docker 部署)。

#### 2. 更新部署步骤

在腾讯云 CVM 上，进入 `InsightBot` 项目目录，执行以下命令：

```bash
# 1. 进入项目目录
cd /path/to/your/InsightBot/project

# 2. 从 GitHub 拉取最新的 main 分支代码
git pull origin main

# 3. 安装或更新 Python 依赖
pip install -r requirements.txt

# 4. 更新环境变量 (如果 .env 文件有变化)
#    确保你的 .env 文件 (或腾讯云的环境变量配置) 包含最新的 AI_API_KEY, AI_API_URL, AI_MODEL 等配置
#    例如，你可以编辑 .env 文件，或者在腾讯云控制台更新环境变量。
#    注意：生产环境的 .env 文件应包含真实的凭证，而不是 .env.local 中的测试凭证。

# 5. 重启 InsightBot 服务
#    根据你的运行方式选择重启命令：
#    - 如果是直接运行 Python 脚本 (例如通过 systemd 或 nohup)：
#      sudo systemctl restart insightbot.service  # 假设你配置了 systemd 服务
#      # 或者手动停止再启动
#      pkill -f smart_brief.py  # 停止旧进程
#      nohup python3 smart_brief.py > insightbot.log 2>&1 & # 启动新进程

#    - 如果是使用 Docker Compose 部署：
#      docker-compose down
#      docker-compose pull  # 拉取最新的镜像 (如果你的 Dockerfile 有更新)
#      docker-compose up -d
```

#### 3. 环境变量管理

*   **推荐**：将敏感信息（如 API Key、Secret）作为腾讯云 CVM 的环境变量进行配置，而不是直接写入代码或 `config.json`。在 `systemd` 服务文件中或 `docker-compose.yml` 中引用这些环境变量。
*   `config.json` 中的 `${VAR_NAME}` 占位符将由我们之前修改的 `insightbot/config.py` 自动替换，这使得配置管理更加灵活和安全。

#### 4. Cron 定时任务

如果 `InsightBot` 依赖于 `cron` 定时任务运行，更新代码后可能需要检查并更新 `crontab` 配置。

```bash
# 查看当前用户的 cron 任务
crontab -l

# 编辑 cron 任务
crontab -e

# 确保 cron 任务中的 Python 路径和脚本路径正确，并且引用了正确的环境变量
# 例如：
# 0 9 * * * cd /path/to/your/InsightBot/project && set -a; source .env; set +a && python3 smart_brief.py >> /var/log/insightbot_cron.log 2>&1
```

### 策略二：使用腾讯云云函数 (SCF) 部署 (如果适用)

如果 `InsightBot` 的运行逻辑可以被封装为无服务器函数，腾讯云 SCF 是一个更具弹性和成本效益的选择。

#### 1. 前提条件

*   已安装腾讯云 CLI 工具或使用腾讯云控制台。
*   `InsightBot` 代码已适配 SCF 运行环境（例如，将核心逻辑封装在 `main` 函数或 `handler` 函数中）。
*   `requirements.txt` 中列出的所有依赖都可以在 SCF 环境中安装。

#### 2. 部署步骤 (以控制台为例)

1.  **打包代码**：将 `InsightBot` 项目打包成 ZIP 文件，包含所有代码和依赖。
2.  **创建/更新函数**：
    *   登录腾讯云 SCF 控制台。
    *   选择或创建一个新的函数服务。
    *   上传你的 ZIP 包。
    *   配置运行时环境 (Python 3.10+)。
    *   配置 **环境变量**：在 SCF 配置中设置 `AI_API_KEY`, `AI_API_URL`, `AI_MODEL`, `WECOM_CID` 等。
    *   配置 **触发器**：设置定时触发器 (Cron 表达式)，例如每天早上 9 点运行。
3.  **测试**：在控制台进行测试，确保函数能正常执行。

#### 3. 环境变量管理 (SCF)

在 SCF 中，环境变量直接在函数配置中管理，这是最安全和推荐的方式。`insightbot/config.py` 中的环境变量替换逻辑将在这里发挥作用。

### 4. 监控与日志

无论哪种部署方式，都应配置相应的监控和日志服务：

*   **CVM**：使用 `systemd` 管理服务，日志输出到 `/var/log/` 或项目内部的 `logs/` 目录，并结合 `logrotate` 进行日志轮转。可以使用腾讯云日志服务 (CLS) 收集和分析日志。
*   **SCF**：SCF 自动集成腾讯云日志服务 (CLS)，可以直接在控制台查看函数运行日志。

---

**重要提示**：在任何生产环境部署之前，务必进行充分的测试，并确保所有敏感信息都已妥善管理，避免硬编码在代码中。
