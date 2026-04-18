# InsightBot 本地测试环境搭建与开发指南

**更新日期**：2026-04-16（适配 v2.0）

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

v2.0 所有调试功能都已集成到管理台，**无需任何命令行调试脚本**。

### 3.1 场景一：任务 Dry Run（tab8 🔬 任务调试）

用于测试"抓取 → AI 筛选 → 生成简报"的完整链路。

**运行方式**：在管理台 tab8 选择任务 → 点击「🔬 Dry Run」。

- 完整 pipeline 执行，但**零频道发送**，结果直接在面板展示
- 显示最终简报 Markdown 预览
- 可展开查看完整中间结果（stage_results）

### 3.2 场景二：Prompt 调优（tab3 🧠 AI 提示词调优）

当发现 AI 筛选不准时，在此调优 Prompt 并草稿试跑。

- 草稿 Prompt 试跑，不影响生产配置
- 当前版 vs 草稿版对比
- 候选池预览
- 最近 20 条调试记录留痕

### 3.3 场景三：RSS 信源健康度（tab4 🩺 RSS 健康度）

用于排查"为什么今天没有推送"的问题。

- 并发检查所有 RSS 源可达性
- 统计近 24 小时文章更新数量
- 区分「正常 / 无更新 / 错误」三态

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

**v2.0 管理台新增功能**：

| Tab | 新增功能 |
|-----|----------|
| tab1 📋 任务管理 | 任务 CRUD、调度时间、频道分配 |
| tab2 📡 Channels | 频道 CRUD + 联通性测试 |
| tab8 🔬 任务调试 | Dry Run 面板（替代旧的 debug_run.py） |
