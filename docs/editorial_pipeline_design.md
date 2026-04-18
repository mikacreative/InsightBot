# InsightBot Editorial Pipeline Design

> Branch: `dev-editorial`  
> Status: Draft + Search Extension  
> Date: 2026-04-08  
> Updated: 2026-04-13

## 1. Goal

将当前“每个板块各自抓取、各自筛选”的流程，升级为更接近编辑部工作流的双阶段流水线：

1. 全局初筛
2. 板块精选与分配

目标不是立即替换现有稳定链路，而是在保留现有工程化约束能力的基础上，提升：

- 全局视角下的选题质量
- 板块之间的去重与优先级一致性
- “今天到底最值得报什么”的整体判断能力

## 2. Current Problems

当前按板块独立筛选的模式存在这些结构性问题：

- 同一条内容可能在多个板块里都显得“还可以”，但缺乏全局优先级
- 板块先天切分后，模型看不到全部候选，容易失去全局排序能力
- 某些高价值内容可能因为源先归在某个板块里，被过早过滤
- 系统更像“多个筛子并排工作”，不像“总编辑先看全局再分栏目”

## 3. Proposed Flow

建议的新流水线：

1. 全量抓取所有订阅源候选
2. 全局初筛
3. 板块分配
4. 板块精选与改写
5. 板块输出与推送

数据流：

```text
all feeds
-> global_candidates
-> global_screened_candidates
-> category_assignment
-> category_candidate_map
-> per-category final selection/rewrite
-> final markdown output
```

## 4. Stage Definitions

### 4.1 Global Candidate Pool

汇总所有 RSS 候选，形成统一候选池。

每条候选建议字段：

- `id`
- `title`
- `link`
- `summary`
- `published_at`
- `source_url`
- `source_name`
- `source_category_hint`

这一层只做工程清洗：

- 近 24h 时间窗
- 按链接去重
- 基础文本清洗
- 可选的标题相似度去重

这一层不做板块判断。

### 4.2 Global Screening

让 AI 先站在“总编辑 / 情报官”的角色，对全局候选做一轮初筛。

这一层关注的问题：

- 哪些内容值得进入今天的 shortlist
- 哪些内容虽然不一定立刻发，但值得保留给板块层继续判断

这一层不直接决定板块归属。

建议输出：

- `items`
- `reason` 或 `editorial_value`
- 可选 `priority_score`

### 4.3 Category Assignment

对通过全局初筛的内容，按板块规则进行归属判断。

当前建议：

- 一条内容只允许单归属
- 不做多板块重复分发

原因：

- 避免重复推送
- 降低板块边界模糊时的结果噪音
- 第一版先验证“全局视角 + 单归属”的价值

建议输出：

- `candidate_id`
- `assigned_category`
- `assignment_reason`

### 4.4 Category Final Selection

板块层只对已经被分配进来的候选做二次精选与改写。

这一层仍然保留当前板块 prompt 的定位：

- 选什么
- 不选什么

板块层不再负责处理全局海量候选，只负责：

- 该板块候选内部排序
- 标题重写
- 摘要生成
- 板块最终条数裁剪

## 5. Design Decisions

### 5.1 Global Screening Multiplier

全局初筛需要一个倍率，避免一开始就只选最终成品数量。

当前建议：

- 先尝试最终输出目标的 `3x`

例如：

- 若单次最终计划总输出约 10 条
- 则全局初筛先保留 30 条左右 shortlist

原因：

- 给板块分配和精选留足空间
- 降低全局初筛过早误杀的风险
- 成本上仍然可控

### 5.2 Single Assignment

当前建议一条内容单归属。

理由：

- 板块是杂志内容的最终结构，不只是标签
- 如果全局阶段已经认定内容有价值，但最终落不到任何板块，说明它和当前刊物结构不匹配
- 多归属会显著提高重复推送和编辑噪音

### 5.3 Empty Category Handling

当前建议：

- 空则空

理由：

- 不为了凑数而降质
- 保持板块语义稳定
- 避免“为了填满栏目而把全局边缘内容硬塞进去”

### 5.4 Debug Entrypoints

这个方案下，调试入口至少需要两个：

1. 全局初筛调试
2. 板块分配 / 板块精选调试

虽然入口变多，但这是流程拆分后的自然结果。目前没有比“双入口”更清晰的方案。

## 6. Prompt Strategy

仍然坚持“工程规则注入，不靠人工手写 schema”。

建议保留可编辑的 prompt 只有两层：

### 6.1 System Prompt

负责：

- 角色定义
- 标题写法
- 摘要写法
- 编辑口径

不负责：

- 条数上限
- JSON schema
- 最大字数
- 分片逻辑

这些规则继续由代码注入。

### 6.2 Category Prompt

负责：

- 该板块选什么
- 不选什么
- 边界条件

不负责通用格式控制。

### 6.3 Should Category Requirements Be Injected Into Global Screening?

这是一个重要问题。

结论：

- 可以部分注入，但不建议把完整板块规则全部塞进全局初筛 prompt

建议做法：

- 向全局初筛注入“刊物整体栏目定位摘要”
- 不注入每个板块的完整细则

原因：

- 这样可以减少“好内容被全局误杀但其实适合某个板块”的问题
- 同时又不会让全局 prompt 过长、过碎、过像多分类器

也就是说：

- 全局层知道“这本杂志大概在关心什么”
- 板块层再决定“它具体属于哪个栏目”

## 7. Cost and Risk Assessment

### 7.1 Cost

成本会提高，但预计不会是不可接受的增长。

原因：

- 现在已经有分片和多轮调用
- 新方案虽然增加了阶段数，但会减少“多个板块重复看同类内容”的冗余
- 全局 shortlist 能让后续板块层只处理更小范围内容

### 7.2 Main Risk: False Negatives

最大的风险不是成本，而是误杀：

- 全局初筛把某些对板块有价值的内容提前过滤掉

缓解方式：

- 使用 `3x` shortlist 倍率
- 向全局层注入刊物整体定位
- 允许先做更宽松的全局初筛，再把精筛压力留给板块层

### 7.3 Unassigned Good Content

如果全局认定有价值，但最终没有落到任何板块，这通常意味着：

- 杂志栏目结构和全局编辑目标不完全匹配

第一版建议不自动补救：

- 不强塞
- 先暴露问题

后续可以再考虑增加“未分配候选观察池”。

## 8. MVP Scope

第一版不要彻底推翻现有链路，建议最小实现为：

1. 新增全局候选池
2. 新增全局初筛
3. 新增单归属板块分配
4. 板块最终改写尽量复用现有逻辑

也就是说，第一版只升级：

- 候选怎么进入板块

先不大改：

- 板块内部最终 markdown 生成方式
- 企业微信推送方式
- 配置文件的大结构

## 9. Suggested Implementation Order

建议开发顺序：

1. 定义 `global_candidates` 数据结构
2. 实现全局初筛函数
3. 实现板块分配函数
4. 接入现有板块最终输出逻辑
5. 补双入口调试面板
6. 加灰度开关，允许新旧流程并存

## 10. Branching Recommendation

建议在独立分支上推进，不直接叠加到现有 `dev` 主线。

当前建议分支：

- `dev-editorial`

这样可以：

- 保持当前 `dev` 继续可用于生产验证
- 让新编辑流水线单独演进
- 便于后续灰度对比新旧方案效果

## 11. Implementation Draft

这一节将设计收敛成可执行的实施稿，目标是回答：

- 第一版具体改哪些文件
- 新增哪些函数
- 哪些逻辑能复用
- 怎么灰度接入而不破坏现有流程

### 11.1 Non-Goals For MVP

第一版明确不做这些事情：

- 不做多板块归属
- 不做正文全文抓取增强
- 不做复杂相似度聚类
- 不改企业微信推送协议
- 不立即替换现有 Prompt Debug 页面为全新控制台

先把主编辑流水线跑通，再考虑增强。

### 11.2 File-Level Change Plan

建议修改/新增这些文件：

#### Existing Files To Update

- [insightbot/smart_brief_runner.py](D:/Documents/GitHub/InsightBot/insightbot/smart_brief_runner.py)
  - 保留现有候选抓取、文本清洗、AI 选择基础设施
  - 增加新流水线入口，但不要删除旧入口

- [scripts/app.py](D:/Documents/GitHub/InsightBot/scripts/app.py)
  - 新增双入口调试面板
  - 新增编辑流水线开关和调试展示

- [config.content.json](D:/Documents/GitHub/InsightBot/config.content.json)
  - 增加 editorial pipeline 相关配置

- [tests/test_smart_brief_runner.py](D:/Documents/GitHub/InsightBot/tests/test_smart_brief_runner.py)
  - 增加新流水线单测

#### New Files To Add

- `insightbot/editorial_pipeline.py`
  - 放新的全局初筛、板块分配、流水线编排逻辑

- `tests/test_editorial_pipeline.py`
  - 覆盖全局初筛、单归属分配、灰度开关

如果后续 UI 逻辑过重，再考虑拆：

- `insightbot/editorial_debug.py`

但第一版不强求。

## 12. Proposed Config Additions

建议在 `config.content.json` 中增加一个独立配置块，而不是把新逻辑散落到现有字段里。

建议结构：

```json
{
  "ai": {
    "system_prompt": "...",
    "selection": {
      "max_selected_items": 5,
      "title_max_len": 50,
      "summary_max_len": 30,
      "full_context_threshold_chars": 18000,
      "batch_size": 15
    },
    "editorial_pipeline": {
      "enabled": false,
      "global_shortlist_multiplier": 3,
      "allow_multi_assign": false,
      "inject_publication_scope_into_global": true,
      "assignment_batch_size": 20
    }
  }
}
```

说明：

- `enabled`
  - 灰度开关
  - `false` 时继续走当前老流程

- `global_shortlist_multiplier`
  - 初筛倍率

- `allow_multi_assign`
  - 第一版默认 `false`

- `inject_publication_scope_into_global`
  - 是否把刊物整体栏目定位摘要注入全局初筛

- `assignment_batch_size`
  - 板块分配阶段的批大小

## 13. Proposed Data Structures

### 13.1 GlobalCandidate

```python
{
  "id": "uuid-or-stable-hash",
  "title": "...",
  "link": "...",
  "summary": "...",
  "published_at": "...",
  "source_url": "...",
  "source_name": "...",
  "source_category_hint": "💡 营销行业"
}
```

### 13.2 ScreenedCandidate

```python
{
  "id": "...",
  "title": "...",
  "link": "...",
  "summary": "...",
  "editorial_reason": "...",
  "priority_score": 0.0
}
```

### 13.3 AssignedCandidate

```python
{
  "id": "...",
  "assigned_category": "🤖 数智前沿",
  "assignment_reason": "..."
}
```

### 13.4 CategoryCandidateMap

```python
{
  "💡 营销行业": [candidate_a, candidate_b],
  "🤖 数智前沿": [candidate_c],
  "📢 政策导向": []
}
```

## 14. Function Interface Draft

建议在 `insightbot/editorial_pipeline.py` 中提供以下函数：

### 14.1 `build_global_candidates`

```python
def build_global_candidates(*, config: dict, logger) -> list[dict]:
    ...
```

职责：

- 抓取所有 RSS 候选
- 统一清洗
- 去重
- 产出统一候选池

### 14.2 `screen_global_candidates`

```python
def screen_global_candidates(
    *,
    config: dict,
    candidates: list[dict],
    logger,
) -> dict:
    ...
```

职责：

- 根据“总编辑”角色做初筛
- 返回 shortlist
- 适配全量 / 分片自适应策略

### 14.3 `assign_candidates_to_categories`

```python
def assign_candidates_to_categories(
    *,
    config: dict,
    screened_candidates: list[dict],
    logger,
) -> dict[str, list[dict]]:
    ...
```

职责：

- 单归属板块分配
- 返回按板块聚合的候选映射

### 14.4 `select_for_category`

```python
def select_for_category(
    *,
    config: dict,
    category_name: str,
    candidates: list[dict],
    logger,
) -> dict:
    ...
```

职责：

- 复用现有板块最终精筛与改写能力

### 14.5 `run_editorial_pipeline`

```python
def run_editorial_pipeline(*, config: dict, logger) -> dict:
    ...
```

职责：

- 串起全局初筛、板块分配、板块最终输出
- 返回调试友好的完整中间结果

## 15. Reuse Strategy

为了控制风险，建议最大化复用现有逻辑：

### 15.1 Reuse Directly

- `fetch_recent_candidates`
- `_render_markdown`
- `_validate_and_repair`
- 现有 AI 调用和结构化输出修复
- 现有 selection settings 注入方式

### 15.2 Reuse With Thin Wrappers

- `run_prompt_debug`
  - 不直接删
  - 作为板块最终精筛的底座，或抽出其中共用部分

### 15.3 Keep Old Pipeline In Place

旧流程第一版不要删除。

保留两个入口：

- `run_task`：当前老流程
- `run_editorial_pipeline`：新流程

再由配置决定走哪条。

## 16. Rollout Strategy

### 16.1 Phase 0: Docs + Branch Only

当前状态。

### 16.2 Phase 1: Hidden Backend Implementation

做后端实现，但默认不开：

- `editorial_pipeline.enabled = false`

目标：

- 能本地调试
- 不影响生产

### 16.3 Phase 2: Debug-Only UI

只在控制台提供调试入口，不接正式推送。

目标：

- 对比新旧流程的候选质量
- 看误杀和分配问题

### 16.4 Phase 3: Optional Runtime Switch

加入显式切换：

- `classic`
- `editorial`

仍然建议默认 `classic`。

### 16.5 Phase 4: Production Trial

只在腾讯云 `dev` 环境试跑：

- 不直接替换 `main`
- 用真实 RSS 和真实模型做 3~7 天观察

## 17. Debug UI Draft

第一版调试 UI 建议增加两个区块：

### 17.1 Global Screening Debug

展示：

- 全局候选池
- 全局初筛 shortlist
- 全局初筛理由
- 是全量还是分片模式

### 17.2 Category Assignment Debug

展示：

- 每条 shortlist 被分配到哪个板块
- 为什么分配到该板块
- 哪些板块为空

### 17.3 Keep Existing Category Prompt Debug

保留现有单板块 Prompt Debug，不立即删除。

原因：

- 它仍然适合做板块层 prompt 微调

## 18. Test Plan

建议新增这些测试：

### 18.1 Global Candidate Tests

- 全量源汇总成功
- 全局候选去重正确

### 18.2 Global Screening Tests

- shortlist 数量符合倍率
- 超阈值时走分片
- 阈值内走全量

### 18.3 Assignment Tests

- 单条内容只归属一个板块
- 不匹配时不强塞
- 空板块允许为空

### 18.4 Rollout Tests

- `enabled=false` 时旧流程不受影响
- `enabled=true` 时新流程入口生效

## 19. MVP Milestone Proposal

建议按这 4 个里程碑推进：

### Milestone A

- 新增 `editorial_pipeline.py`
- 完成全局候选池与全局初筛

### Milestone B

- 完成单归属板块分配
- 可输出 `category_candidate_map`

### Milestone C

- 接入板块最终精筛
- 跑通完整 debug 链路

### Milestone D

- 控制台双入口调试
- 灰度开关
- 腾讯云 `dev` 验证

## 20. Decision Summary

当前实施稿采用以下明确决策：

- 默认单归属
- 空则空
- 全局初筛倍率先用 `3x`
- 全局层只注入“刊物整体栏目定位摘要”，不注入每个板块完整规则
- MVP 先做新旧流程并存，不替换老流程

这意味着第一版的成功标准不是“立刻上线替换”，而是：

- 在 `dev-editorial` 上形成可调试、可比较、可灰度的新流水线
- 用真实运行结果证明它比现有逐板块独立筛选更像一个"编辑系统"

---

## 21. Search Integration — 搜索补充能力

> 状态：设计稿，待实现

### 21.1 定位

搜索是**全局候选池的补充数据源**，与 RSS 抓取**并行**执行，结果合并后一同进入全局初筛。

```
Stage 1（重构后）:
  ┌─ RSS 源抓取 ────────────────────┐
  │  build_global_candidates()          │  现有逻辑
  └────────────────────────────────────┘
                    ↕ 并行
  ┌─ 搜索引擎查询 ────────────────────┐
  │  search_global_candidates()         │  新增
  └────────────────────────────────────┘
                    ↓
           合并 → 去重 → 全局初筛
```

**设计原则：**
- 搜索结果与 RSS 结果走**完全相同的 pipeline**（同一 screening、同一分配）
- 不为搜索结果设计旁路或单独的质量阈值
- 搜索是**可关闭的**，默认关闭
- `category_hint` 只做参考权重，不强制匹配

### 21.2 为什么不直接抓搜索结果正文

搜索结果的 snippet 摘要已经包含了内容的核心信息，足够 AI 做"是否值得进入简报"的初筛判断。全文抓取会引入：

- 额外网络延迟（搜索结果 URL 通常响应不稳定）
- 反爬虫风险
- 筛选链路延迟大幅增加

第一版只依赖 snippet，够用。

### 21.3 搜索引擎选型

| Provider | 适用场景 | 依赖 | 备注 |
|----------|----------|------|------|
| `baidu` | 腾讯云内地节点 | 无 | 国内可访问，默认生产配置 |
| `duckduckgo` | 海外节点 / 本地开发 | `duckduckgo-search` | 腾讯云内地可能访问受限 |

通过 `search.provider` 配置切换，不影响 pipeline 逻辑。

```json
{
  "search": {
    "enabled": false,
    "provider": "baidu",
    "queries": [...]
  }
}
```

### 21.4 配置结构

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

### 21.5 category_hint 自动生成

启用搜索时，如果 `queries` 为空，系统自动用各板块的 `keywords` 和 `prompt` 生成初始 query：

```
# 自动生成的 query 格式：
板块 keywords 拼接 + 板块 prompt 摘要前 20 字
```

管理员在控制台 tab7 看到自动生成的 queries，再手动确认或调整。

### 21.6 数据结构

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

### 21.7 函数设计

#### `search_global_candidates(*, config, logger) -> list[GlobalCandidate]`

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

#### `build_global_candidates` 改造

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

### 21.8 搜索引擎接口抽象

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

### 21.9 控制台 UI（tab7 扩展）

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

### 21.10 实现优先级

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

### 21.11 关键决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| 搜索关键词来源 | A：管理员手动配置 | 可控、符合现有运营习惯 |
| 搜索摘要粒度 | A：纯 snippet 够用 | 快、无额外延迟、够用于初筛判断 |
| 搜索引擎 | baidu（默认，腾讯云）/ duckduckgo（可选） | 内地节点访问百度更稳定 |
| category_hint 默认值 | 启用时自动从板块 keywords 生成 | 降低初始配置门槛 |
| category_hint 匹配方式 | 参考权重，非强制 | 防止硬塞，保持全局初筛的独立性 |
