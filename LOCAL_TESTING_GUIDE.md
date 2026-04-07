# InsightBot 本地测试环境搭建与开发指南

**作者**：Manus AI
**日期**：2026年3月19日

为了在本地对 InsightBot 进行持续优化（如调整 AI Prompt、增加新信源解析逻辑）而不影响生产环境，我们设计了一套完整的本地测试框架。本指南将指导你如何快速搭建并使用这套环境。

---

## 1. 环境隔离策略

本地测试环境的核心原则是**与生产环境完全隔离**：
- **配置隔离**：使用 `.env.local`、`config.local.content.json` 和 `config.local.secrets.json`，不读取生产配置。
- **日志隔离**：所有本地运行日志输出到 `logs_local/` 目录。
- **推送隔离**：提供 `DRY_RUN` 模式（仅输出到本地文件），或配置专用的测试企业微信 Agent ID。

---

## 2. 快速搭建步骤

### 2.1 准备 Python 虚拟环境
建议使用 Python 3.10+，并在项目根目录创建虚拟环境：
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
*(注：`requirements.txt` 中已补充 `pytest` 和 `pytest-mock` 等测试依赖)*

### 2.2 初始化本地配置
项目根目录已提供模板文件，直接复制并修改：

1. **环境变量配置**：
   ```bash
   cp .env.local.example .env.local
   ```
   打开 `.env.local`，填入你的测试用 API Key 和企业微信凭证（如果开启了 `DRY_RUN=1`，企业微信凭证可以随便填）。

2. **内容配置**：
   ```bash
   cp config.content.json config.local.content.json
   ```
   这是一个可安全纳入版本控制的配置，包含用于测试的 RSS 源、版式与 Prompt。

3. **敏感信息配置**：
   ```bash
   cp config.secrets.example.json config.local.secrets.json
   ```
   打开 `config.local.secrets.json`，填入测试用 API Key 和企业微信凭证；或完全通过 `.env.local` 提供。

---

## 3. 调试工具与工作流

我们为你编写了三个强大的本地调试脚本，覆盖了日常开发的各种场景。

### 3.1 场景一：完整流程调试 (`debug_run.py`)
用于测试"抓取 -> AI 筛选 -> 生成报告"的完整链路。

默认开启了 `DRY_RUN` 模式，**不会向企业微信发送消息**，而是将最终的 Markdown 报告输出到 `logs_local/dry_run_report.md`。

**运行方式**：
```bash
# 加载本地环境变量并运行
set -a; source .env.local; set +a
export CONFIG_CONTENT_FILE=./config.local.content.json
export CONFIG_SECRETS_FILE=./config.local.secrets.json
python debug_run.py
```
运行结束后，直接使用 Markdown 编辑器打开 `logs_local/dry_run_report.md` 即可预览推送效果。

### 3.2 场景二：AI Prompt 调优 (`debug_prompt.py`)
当发现 AI 筛选不准、或者总是返回 `NONE` 时，使用此脚本可以**针对单个板块**快速测试 Prompt。

**运行方式**：
```bash
set -a; source .env.local; set +a
export CONFIG_CONTENT_FILE=./config.local.content.json
export CONFIG_SECRETS_FILE=./config.local.secrets.json

# 1. 使用本地内容配置中的 RSS 源实时抓取，测试指定板块
python debug_prompt.py --category "📢 测试板块-营销行业"

# 2. 如果 RSS 源暂时没更新，可以使用内置的模拟新闻列表强制测试
python debug_prompt.py --category "📢 测试板块-营销行业" --mock-news

# 3. 临时覆盖 Prompt 进行对比测试（不修改配置文件）
python debug_prompt.py --category "📢 测试板块-营销行业" --mock-news --prompt "只保留有具体数据支撑的营销案例"
```
该脚本会打印出喂给 AI 的完整新闻列表，以及 AI 的**原始响应内容**，极大地提升了 Prompt 调优效率。

### 3.3 场景三：RSS 信源健康度检查 (`debug_rss_check.py`)
用于排查"为什么今天没有推送"的问题。它会并发检查配置文件中所有 RSS 源的可达性，并统计近 24 小时的文章更新数量。

**运行方式**：
```bash
set -a; source .env.local; set +a
export CONFIG_CONTENT_FILE=./config.local.content.json
export CONFIG_SECRETS_FILE=./config.local.secrets.json
python debug_rss_check.py
```

---

## 4. 自动化测试套件 (Pytest)

为了保障核心逻辑在重构或修改后不被破坏，我们在 `tests/` 目录下建立了自动化测试套件。

### 4.1 测试覆盖范围
- `test_ai.py`：AI 模块的请求组装、异常处理。
- `test_wecom.py`：企业微信 Token 获取与 Markdown 推送逻辑。
- `test_smart_brief_runner.py`：核心业务逻辑，包括：
  - **时效性过滤**：准确拦截 24 小时前的文章。
  - **链接去重**：准确过滤重复链接。
  - **NONE 拦截**：AI 返回 NONE 时正确阻断推送。
- `test_config_paths.py`：路径优先级与配置加载逻辑。

### 4.2 运行测试
在项目根目录执行：
```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块的测试
pytest tests/test_smart_brief_runner.py -v
```
测试套件使用了 `pytest-mock` 拦截了所有外部网络请求，并使用了 `tests/fixtures/` 下的静态 XML 文件模拟 RSS 源，因此**运行测试不需要真实的 API Key，也不会产生任何网络费用**。

---

## 5. 本地启动控制台 (Streamlit)

如果你想在本地测试 Streamlit UI 的交互逻辑：
```bash
set -a; source .env.local; set +a
streamlit run scripts/app.py
```
此时控制台读取和修改的都是 `config.local.content.json`，敏感信息来自 `config.local.secrets.json` 或环境变量；点击"立即手动运行"触发的也是本地的测试配置，完全不会影响生产环境。
