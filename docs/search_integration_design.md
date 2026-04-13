# Editorial Pipeline — 搜索补充能力设计

> Branch: `dev-editorial`
> Status: Design Draft
> Date: 2026-04-13

## 1. 定位

搜索是**全局候选池的补充数据源**，与 RSS 抓取**并行**执行，结果合并后一同进入全局初筛。

```
Stage 1（重构后）:
  ┌─ RSS 源抓取 ────────────────────┐
  │  build_global_candidates()          │  现有逻辑
  └────────────────────────────────────┘
                    ↕ 并行
  ┌─ 搜索引擎查询 ────────────────────┐
  │  search_global_candidates()           │  新增
  └────────────────────────────────────┘
                    ↓
           合并 → 去重 → 全局初筛
```

**设计原则：**
- 搜索结果与 RSS 结果走**完全相同的 pipeline**（同一 screening、同一分配）
- 不为搜索结果设计旁路或单独的质量阈值
- 搜索是**可关闭的**，默认关闭
- `category_hint` 只做参考权重，不强制匹配

## 2. 为什么不直接抓搜索结果正文

搜索结果的 snippet 摘要已经包含了内容的核心信息，足够 AI 做"是否值得进入简报"的初筛判断。全文抓取会引入：

- 额外网络延迟（搜索结果 URL 通常响应不稳定）
- 反爬虫风险
- 筛选链路延迟大幅增加

第一版只依赖 snippet，够用。

## 3. 搜索引擎选型

| Provider | 适用场景 | 依赖 | 备注 |
|----------|----------|------|------|
| `baidu` | 腾讯云内地节点 | 无 | 国内可访问，默认生产配置 |
| `duckduckgo` | 海外节点 / 本地开发 | `duckduckgo-search` | 腾讯云内地可能访问受限 |

通过 `search.provider` 配置切换，不影响 pipeline 逻辑。

## 4. 配置结构

在 `config.content.json` 根层加 `search` 块，与 `feeds` 同级：

```json
{
  "feeds": { ... },
  "search": {
    "enabled": false,
    "provider": "baidu",
    "queries": [
      {
        "keywords": "品牌 AI 营销 新动作 2024",
        "category_hint": "💡 营销行业",
        "max_results": 10
      },
      {
        "keywords": "数字营销 平台更新 动态",
        "category_hint": "🤖 数智前沿",
        "max_results": 10
      },
      {
        "keywords": "广告监管 品牌合规 政策",
        "category_hint": "📢 政策导向",
        "max_results": 10
      }
    ]
  }
}
```

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `enabled` | 是 | 搜索补充总开关 |
| `provider` | 否 | `baidu`（默认）或 `duckduckgo` |
| `queries` | 是 | 查询列表，每条对应一个搜索意图 |
| `queries[].keywords` | 是 | 搜索关键词，多个词用空格分隔 |
| `queries[].category_hint` | 否 | 搜索结果优先进入的板块（参考权重，非强制） |
| `queries[].max_results` | 否 | 最大结果数，默认 10 |

## 5. category_hint 自动生成

启用搜索时，如果 `queries` 为空，系统自动用各板块的 `keywords` 和 `prompt` 生成初始 query：

```
# 自动生成的 query 格式：
板块 keywords 拼接 + 板块 prompt 摘要前 20 字
```

管理员在控制台 tab7 看到自动生成的 queries，再手动确认或调整。

## 6. 数据结构

```python
# 搜索结果原始格式
{
  "title": "...",
  "link": "...",
  "snippet": "...",
  "query": "品牌 AI 营销 新动作 2024",
  "provider": "baidu",
}

# 归一化为 GlobalCandidate（与 RSS 候选同格式）
{
  "id": "hash(link)",
  "title": "[搜索] 原始标题",
  "link": "...",
  "summary": "snippet 清洗结果",
  "published_at": "",                    # 搜索结果无时间，取空
  "source_url": "...",
  "source_name": "搜索结果",
  "source_category_hint": "💡 营销行业",   # 来自 category_hint 或空
  "source_type": "search"                 # 区分来源：rss | search
}
```

**归一化时注意：**
- `source_type = "search"` 标记，方便在调试面板区分来源
- 标题加 `[搜索]` 前缀，让 AI 在全局初筛时知道内容来自搜索结果
- `published_at` 为空，初筛时由 AI 根据内容新鲜度自行判断

## 7. 函数设计

### `search_global_candidates(*, config, logger) -> list[GlobalCandidate]`

```python
def search_global_candidates(*, config: dict, logger) -> list[dict]:
    """
    读取 config["search"]，执行搜索引擎查询，归一化为 GlobalCandidate。
    搜索引擎可插拔（baidu / duckduckgo）。
    """
    search_config = config.get("search", {})
    if not search_config.get("enabled", False):
        return []

    provider = search_config.get("provider", "baidu")
    queries = search_config.get("queries", [])
    all_results: list[dict] = []

    for q in queries:
        keywords = q.get("keywords", "").strip()
        if not keywords:
            continue
        max_results = q.get("max_results", 10)
        category_hint = q.get("category_hint", "")

        raw_results = _call_search_engine(provider, keywords, max_results)
        for r in raw_results:
            normalized = _normalize_search_result(r, category_hint=category_hint)
            all_results.append(normalized)

    # 同 link 去重
    unique = _deduplicate_candidates(all_results)
    logger.info(f"🔍 搜索补充：{len(unique)} 条（来自 {len(queries)} 个 query）")
    return unique
```

### `build_global_candidates` 改造

```python
def build_global_candidates(*, config: dict, logger) -> list[dict]:
    # 1. RSS 候选（现有逻辑，保持不变）
    rss_candidates = _fetch_all_feeds(config, logger)

    # 2. 搜索候选（新增，并行）
    search_candidates = search_global_candidates(config=config, logger=logger)

    # 3. 合并 + 全局去重（按 link）
    all_candidates = rss_candidates + search_candidates
    unique = _deduplicate_candidates(all_candidates)
    logger.info(f"📦 全局候选池：RSS {len(rss_candidates)} + 搜索 {len(search_candidates)} = 合并去重后 {len(unique)} 条")
    return unique
```

## 8. 搜索引擎接口抽象

```python
def _call_search_engine(provider: str, keywords: str, max_results: int) -> list[dict]:
    if provider == "baidu":
        return _search_baidu(keywords, max_results)
    elif provider == "duckduckgo":
        return _search_duckduckgo(keywords, max_results)
    else:
        raise ValueError(f"Unknown search provider: {provider}")

def _search_baidu(keywords: str, max_results: int) -> list[dict]:
    """
    使用 requests + BeautifulSoup 搜索百度。
    腾讯云内地节点可正常访问。
    """
    ...

def _search_duckduckgo(keywords: str, max_results: int) -> list[dict]:
    """
    复用现有 insightbot.discovery.search.SearchStrategy 逻辑。
    """
    ...
```

## 9. 控制台 UI（tab7 扩展）

在 tab7 现有"Editorial Pipeline 全局设置"区块下增加搜索配置：

```
┌─ 🔍 搜索补充配置 ──────────────────────────────────────────┐
│                                                               │
│  [✓] 启用搜索补充                                            │
│  搜索引擎: ( ○ 百度  ● DuckDuckGo )                          │
│                                                               │
│  ┌─ 查询 1 ───────────────────────────────────────────┐   │
│  │  关键词: [品牌 AI 营销 新动作 2024                 ]   │   │
│  │  板块Hint: [💡 营销行业 ▼] (留空则不预设板块)        │   │
│  │  最大结果: [10]                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  [+ 添加查询]    [🗑️ 全部清除]                               │
│                                                               │
│  💡 提示: 启用搜索时留空 queries，系统会用各板块 keywords      │
│     自动生成初始查询。                                         │
└───────────────────────────────────────────────────────────────┘
```

**初始 query 生成逻辑（控制台侧）：**
- 管理员勾选"启用搜索补充"
- 如果 queries 为空，自动从各板块 keywords 派生：
  ```
  for each category:
    query.keywords = category.keywords.join(" ")
    query.category_hint = category.name
    query.max_results = 10
  ```
- 管理员确认或手动调整

## 10. 实现优先级

**Phase 1（MVP）：**
- `search_global_candidates()` 函数
- 仅 `baidu` provider（腾讯云兼容性）
- 与 `build_global_candidates()` 集成
- 搜索结果纳入全局初筛（同一 shortlist 逻辑）

**Phase 2（体验增强）：**
- 控制台 tab7 搜索配置 UI
- category_hint 自动生成
- `duckduckgo` provider 作为可选项

**不在第一版范围内：**
- 全文抓取搜索结果 URL
- 搜索结果单独的质量阈值/过滤规则
- 搜索 query 的 AI 生成/优化

## 11. 关键决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| 搜索关键词来源 | A：管理员手动配置 | 可控、符合现有运营习惯 |
| 搜索摘要粒度 | A：纯 snippet 够用 | 快、无额外延迟、够用于初筛判断 |
| 搜索引擎 | baidu（默认，腾讯云）/ duckduckgo（可选） | 内地节点访问百度更稳定 |
| category_hint 默认值 | 启用时自动从板块 keywords 生成 | 降低初始配置门槛 |
| category_hint 匹配方式 | 参考权重，非强制 | 防止硬塞，保持全局初筛的独立性 |
