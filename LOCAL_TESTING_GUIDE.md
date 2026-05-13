# InsightBot 本地测试环境搭建与开发指南

**更新日期**：2026-04-29（适配当前 `dev-editorial` 基线）

---

## 1. 环境隔离策略

本地测试环境的核心原则是**与生产环境完全隔离**：
- **配置隔离**：使用 `.env.local`、`config.local.content.json` 和 `config.local.secrets.json`，不读取生产配置。
- **日志隔离**：所有本地运行日志输出到 `logs_local/` 目录。
- **推送隔离**：提供 `INSIGHTBOT_DRY_RUN=1` 模式（强制所有频道发送进入测试模式），或配置专用的测试企业微信 Agent ID。

---

## 2. 快速搭建步骤

### 2.1 准备 Python 虚拟环境

建议使用 Python 3.10+，并在项目根目录创建虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.2 初始化本地配置

项目根目录已提供模板文件，直接复制并修改：

1. **环境变量配置**：
   ```bash
   cp .env.local.example .env.local
   ```
   打开 `.env.local`，填入测试用 API Key 和企业微信凭证（如果开启了 `INSIGHTBOT_DRY_RUN=1`，企业微信凭证可以随便填）。

2. **内容配置**：
   ```bash
   cp config.content.json config.local.content.json
   ```
   这是一个可安全纳入版本控制的配置，包含用于测试的 RSS 源、版式与 Prompt。

3. **敏感信息配置**：
   ```bash
   cp config.secrets.example.json config.local.secrets.json
   ```
   打开 `config.local.secrets.json`，填入测试用 API Key 和企业微信凭证；或完全通过 `.env.local` 中的环境变量提供。

---

## 3. 调试工具与工作流

当前开发基线下，所有高频调试功能都已集成到管理台，**无需任何命令行调试脚本**。

### 3.1 场景一：任务 Dry Run（`🔬 任务调试`）

用于测试"抓取 → AI 筛选 → 生成简报"的完整链路。

**运行方式**：在管理台 `🔬 任务调试` 选择任务 → 点击「🔬 Dry Run」。

- 完整 pipeline 执行，但**零频道发送**，结果直接在面板展示
- 显示最终简报 Markdown 预览
- 可展开查看完整中间结果（stage_results）

### 3.2 场景二：板块调试（`🧪 验证与调试`）

当发现 AI 筛选不准、栏目分配异常，或需要验证草稿 Prompt 时，在这里就地调试。

- 选择当前调试板块
- 抓候选、试跑草稿 Prompt，不影响生产配置
- 当前版 vs 草稿版对比
- 可在确认后写回任务配置
- 最近调试记录留痕

### 3.3 场景三：健康检查与 No Push Diagnosis（`🧪 验证与调试`）

用于排查“为什么某次没有推送”“为什么候选不够”“为什么板块没分到内容”。

- 并发检查 RSS 源可达性
- 统计近 24 小时文章更新数量
- 区分「正常 / 无更新 / 错误」三态
- 同页查看 No Push Diagnosis、日志摘要和板块调试入口

---

## 4. 自动化测试套件 (Pytest)

在 `tests/` 目录下建立了自动化测试套件，保障核心逻辑在重构或修改后不被破坏。

### 4.1 测试覆盖范围

| 文件 | 测试范围 |
|------|----------|
| `test_ai.py` | AI 模块的请求组装、异常处理 |
| `test_wecom.py` | 企业微信 Token 获取与 Markdown 推送逻辑 |
| `test_smart_brief_runner.py` | 经典简报流程，run_task() 返回 final_markdown |
| `test_editorial_pipeline.py` | Editorial Pipeline 各阶段正确返回 |
| `test_config_paths.py` | 路径优先级与配置加载逻辑 |
| `test_channels.py` | Channel 抽象层、send/test/dry_run 逻辑 |
| `test_scheduler.py` | 调度器时间/idempotency/.reload |
| `test_task_runner.py` | dry_run vs 真实发送、pipeline dispatch |
| `test_migrate.py` | v1 → v2 自动迁移逻辑 |

### 4.2 运行测试

在项目根目录执行：

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块的测试
pytest tests/test_scheduler.py -v
```

测试套件使用 `tests/fixtures/` 下的静态 XML 文件模拟 RSS 源，并 mock 了所有 AI API 调用，**运行测试不需要真实的 API Key，也不会产生任何网络费用**。

---

## 5. 本地启动控制台 (Streamlit)

```bash
set -a; source .env.local; set +a
streamlit run scripts/app.py --server.address 0.0.0.0 --server.port 8501
```

管理台读取 `config.local.content.json`，敏感信息来自 `config.local.secrets.json` 或环境变量，不影响生产配置。

**当前管理台主标签页**：

| Tab | 新增功能 |
|-----|----------|
| `🏠 概览` | 当前任务运营总览、异常摘要、最近调试动态 |
| `📋 任务管理` | 任务 CRUD、feeds/search/pipeline/channels/schedule |
| `📡 Channels` | 频道 CRUD + 联通性测试 |
| `🧪 验证与调试` | 健康检查、No Push Diagnosis、板块调试、日志摘要 |
| `📝 运行日志` | 当前任务优先的运行日志追踪 |
| `⚙️ 推送版式定制` | 标题、无更新提示语、底部链接 |
| `🔬 任务调试` | Dry Run 面板（零频道发送） |
