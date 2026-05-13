# Editorial Intelligence Skill System 设计稿

> 状态：Draft  
> 适用范围：InsightBot 下一阶段底层能力重构  
> 文档目标：定义“面向情报生产的 agent skill system”的命名、边界、架构和演进路线

## 1. 为什么要从脚本升级成 Skill System

当前 InsightBot 已经在产品层取得了两个关键进展：

- v2.0 完成了多任务、多频道、调度和任务型控制台底座
- v2.1 正在补任务状态、运行历史、验证与诊断闭环

但底层执行层仍然偏“脚本化”：

- 主要依赖预先指定的 RSS 源
- 搜索是补充能力，不是同等公民
- 流程大体是固定的线性 pipeline
- 模型主要承担筛选和生成，不真正承担“探索下一步”的职责

这在以下场景里会逐渐不够用：

- 指定源不够丰富，漏掉重要信息
- 指定源噪音大，需要动态降权或替换
- 某个主题在搜索结果或平台源里更活跃，而不在 RSS 里
- 不同任务对“探索深度”和“证据密度”的要求不同
- 未来接入更多外部平台时，固定脚本会迅速膨胀

因此，下一阶段不应只是继续堆脚本，而应把底层抽象成：

**一个以 editorial workflow 为核心、支持多源混合检索和动态补源的 agent skill system。**

---

## 2. 命名目标

这个名字需要同时满足四个要求：

1. 能表达“情报生产 / 简报生成”，不是通用 agent 平台
2. 能表达 editorial workflow，而不是简单抓 RSS
3. 后续既可作为产品底层能力名，也可单独抽成 skill 名
4. 足够稳定，不会因为以后增加搜索、平台源而失真

---

## 3. 名字候选

### 3.1 推荐名

## **Editorial Intelligence Skill System**

推荐简称：

- `EISS`
- 中文可称：**编辑式情报技能系统**

推荐原因：

- `Editorial` 明确强调它不是纯抓取器，而是带编辑判断的工作流
- `Intelligence` 比 `news` 更宽，适合行业信息、市场信号、舆情、研究素材
- `Skill System` 明确它不是单一脚本，也不是完整产品后台，而是一组可复用能力

这个名字既适合作为总架构名，也适合作为能力层名称。

### 3.2 次优方案

1. **Editorial Briefing Engine**
   适合强调“生成简报”的结果导向，但对多源探索和诊断能力表达偏弱。

2. **Intelligence Briefing Runtime**
   更偏 runtime 层语义，适合技术架构文档，但对最终产品体验不如 `Skill System` 自然。

3. **Signal Briefing System**
   更轻、更产品化，但 `signal` 的含义对非内部成员不够直观。

4. **Editorial Signal Engine**
   突出“从信号到编辑成稿”，但对“技能系统”语义表达不足。

### 3.3 不推荐方案

- `News Skill`
  太窄，后续做行业研究、市场观察、平台内容时会显得受限。

- `RSS Agent`
  过度绑定当前技术形态。

- `OpenClaw-like Runtime`
  把问题定义成“像某个框架”，不利于形成自己的能力边界。

---

## 4. 建议的命名层级

为了避免一个名字承担所有职责，建议分三层命名：

### 产品层

- `InsightBot`

职责：

- 多任务运营台
- 调度与投递
- 运行历史
- 验证与诊断
- 任务管理与系统配置

### 能力层

- `Editorial Intelligence Skill System`

职责：

- 面向情报生产的一组技能和工作流
- 多源检索、补源、筛选、编辑、成稿

### 核心技能

- `editorial-briefing`

职责：

- 接收一个 briefing 目标
- 执行一次完整的情报生产流程
- 返回结构化中间结果与最终简报

也就是说：

- `InsightBot` 是产品
- `Editorial Intelligence Skill System` 是能力层
- `editorial-briefing` 是第一号核心 skill

---

## 5. 系统边界

这个系统不是要替换整个 InsightBot，而是明确拆出“能力层”和“产品层”。

### 产品层负责什么

- 多任务配置
- 频道与调度
- 运行历史
- 配置完整性校验
- 健康缓存
- 任务状态
- 验证与诊断
- 控制台 UI

### Skill System 负责什么

- 根据 briefing 目标构造 source strategy
- 从多源收集候选信号
- 判断是否需要进一步补源
- 做 shortlist / assignment / refinement
- 生成 final brief
- 输出中间证据和诊断信息

### 不建议由 Skill System 负责什么

- 直接承担完整多任务调度
- 长期历史存储
- 任务级权限与后台管理
- 完整的投递控制台

一句话：

**Skill System 是生产引擎，不是运营后台。**

---

## 6. 三层架构

建议整体拆成三层：

### 6.1 Runtime Layer

这是“怎么决定下一步动作”的层。

职责：

- 管理一次执行的上下文
- 调度不同 source adapter / tool
- 管理探索与补源策略
- 控制执行预算、重试、回退
- 记录中间状态和证据

这一层应具备：

- 轻量 planning
- 工具调用能力
- 中间结果存储
- source adapter 注册机制
- 失败恢复与超时控制
- execution mode 支持

这一层不应该写死为单一 RSS 脚本。

### 6.2 Skill Layer

这是“完成一类情报生产任务”的层。

第一优先 skill：

- `editorial-briefing`

它负责：

1. 理解 briefing 目标
2. 组装 source strategy
3. 产出候选池
4. 进行 editorial shortlist
5. 完成栏目分配
6. 完成编辑润色与成稿
7. 返回结构化结果

后续可扩展的 sibling skills：

- `source-discovery`
- `signal-diagnosis`
- `brief-rewrite`
- `channel-packaging`

### 6.3 Product Layer

也就是当前 InsightBot 控制台。

它负责把 task 配置、运行记录、诊断和投递能力组织成一个可持续运营的产品。

---

## 7. 核心理念

这个系统需要和“固定脚本 + 单点 prompt”有明显区别。

### 7.1 Source Strategy First

过去是：

- 任务 = 固定 feeds 列表

以后应该是：

- 任务 = 目标 + source strategy + editorial policy

也就是说，源不再只是静态列表，而是一个策略对象。

它应支持：

- RSS
- 搜索
- 平台 adapter
- 手工种子源
- 黑白名单
- 动态权重

### 7.2 Agentic Workflow, Not Just Linear Pipeline

过去更像：

1. 抓
2. 筛
3. 发

以后应该更像：

1. 先探索已知源
2. 判断候选是否足够
3. 不足则触发补源
4. 聚合并统一归一化
5. 做 shortlist
6. 做栏目分配
7. 做编辑润色
8. 生成 final brief 和诊断结果

### 7.3 Intermediate Results Are First-Class

中间结果不应只是临时变量，而应成为一等输出：

- raw signals
- normalized candidates
- shortlist
- assignment result
- rejected reasons
- diagnostics
- final brief

这会直接影响：

- Prompt Debug
- 验证与诊断
- 质量优化
- 人类编辑介入

---

## 8. 核心对象模型

建议引入以下核心对象。

### 8.1 BriefingGoal

描述这次要产出什么。

建议字段：

- `topic`
- `audience`
- `brief_type`
- `focus_areas`
- `exclusions`
- `time_window`
- `quality_bar`

### 8.2 SourceStrategy

描述“从哪里找，优先找什么，什么时候补源”。

建议字段：

- `primary_sources`
- `fallback_sources`
- `search_enabled`
- `platform_enabled`
- `max_explore_rounds`
- `coverage_threshold`
- `freshness_threshold`
- `source_constraints`

### 8.3 EditorialPolicy

描述怎么取舍和怎么写。

建议字段：

- `shortlist_size`
- `selection_rules`
- `section_rules`
- `dedupe_rules`
- `tone`
- `citation_style`
- `quality_checks`

### 8.4 ExecutionMode

描述这次执行更偏哪种策略。

建议枚举：

- `fast_run`
- `production_run`
- `explore_heavy`
- `source_constrained`
- `diagnostic_run`

### 8.5 BriefingResult

统一的一次 skill 输出。

建议包含：

- `goal`
- `source_summary`
- `raw_signal_count`
- `candidate_count`
- `shortlist`
- `section_assignments`
- `final_brief`
- `diagnostics`
- `artifacts`

---

## 9. Source Adapter 设计

多源能力不应在 skill 里硬编码，而应通过 adapter 机制接入。

### 9.1 Adapter 类型

- `rss_adapter`
- `search_adapter`
- `platform_adapter`
- `document_adapter`
- `api_adapter`

### 9.2 Adapter 统一输出

无论来自 RSS、搜索还是平台，都应统一归一化成同一种候选结构，例如：

```json
{
  "source_type": "rss",
  "source_id": "36kr_rss",
  "title": "...",
  "summary": "...",
  "url": "...",
  "published_at": "...",
  "signals": {
    "freshness_score": 0.82,
    "relevance_hint": "...",
    "source_weight": 0.75
  },
  "raw": {}
}
```

这样后续 shortlist 和 assignment 才能真正与 source 解耦。

### 9.3 Adapter 设计原则

- 输入统一
- 输出统一
- 可缓存
- 可诊断
- 可统计成功率与命中率

---

## 10. `editorial-briefing` 核心执行流

建议第一版 skill 的执行流如下：

### Step 1：Interpret Goal

将任务配置、主题和执行模式整理成统一的 `BriefingGoal`。

### Step 2：Build Source Strategy

根据任务配置和 execution mode 生成 source strategy：

- 先用指定 feeds
- 判断是否启用 search
- 判断是否允许平台补源

### Step 3：Collect Primary Signals

从主要源收集候选信号。

### Step 4：Coverage Check

判断当前候选是否足够：

- 数量是否足够
- 新鲜度是否足够
- 主题覆盖是否足够
- 重要板块是否缺失

### Step 5：Supplement Sources

若不足，则触发：

- search 补源
- fallback 源
- 平台源

### Step 6：Normalize + Dedupe

将所有来源统一归一化并去重。

### Step 7：Editorial Shortlist

从全局候选池中选出真正值得进入编辑流程的候选。

### Step 8：Section Assignment

将 shortlist 内容分配到栏目。

### Step 9：Refine Per Section

按栏目生成最终条目。

### Step 10：Assemble Final Brief

组装最终简报，并返回结构化结果。

### Step 11：Emit Diagnostics

补充输出：

- 哪些板块缺信号
- 哪些源失效
- 为什么结果偏少
- 哪一轮补源最有价值

---

## 11. Skill 输入输出契约

### 输入

第一版建议最小输入如下：

```json
{
  "goal": {},
  "source_strategy": {},
  "editorial_policy": {},
  "output_contract": {
    "include_candidates": true,
    "include_diagnostics": true,
    "include_final_brief": true
  },
  "execution_mode": "production_run"
}
```

### 输出

建议返回：

```json
{
  "ok": true,
  "goal": {},
  "source_summary": {},
  "candidate_pool": [],
  "shortlist": [],
  "section_assignments": {},
  "final_brief": {
    "markdown": "..."
  },
  "diagnostics": {
    "coverage_gaps": [],
    "source_failures": [],
    "needs_more_exploration": false
  },
  "artifacts": {}
}
```

重点：

- skill 不只返回 final markdown
- 必须把中间层显式返回

---

## 12. 与当前 InsightBot 的关系

建议不要推翻当前产品，而是逐步内嵌替换底层。

### 当前阶段

- 控制台仍是 InsightBot
- `task_runner` 仍是统一执行入口
- `editorial_pipeline` 仍是当前主要生产流

### 下一阶段

把 `editorial_pipeline` 逐步演化成：

- `editorial-briefing` skill 的具体实现

并让 `task_runner` 调用的是：

- skill execution

而不是一段固定脚本。

### 最终形态

- InsightBot = 产品壳
- Editorial Intelligence Skill System = 底层能力层
- `editorial-briefing` = 核心 skill

---

## 13. 为什么这比“继续写脚本”更值得

### 更灵活

面对源不全、源变动、平台迁移时，不必每次改整段固定流程。

### 更可扩展

以后接搜索、社媒、社区、私有 API，不需要重写 pipeline 主体。

### 更可诊断

中间结果一等公民后，控制台更容易解释“为什么没产出”。

### 更可复用

这个 skill 将来可以脱离 InsightBot 单独被其他 agent 或产品调用。

---

## 14. 第一版落地建议

不要一次把 runtime 全部 agent 化，建议分 3 步走。

### Phase 1：Skill 化现有 Editorial Pipeline

目标：

- 保持现有 editorial 结果基本不变
- 把执行接口从“脚本函数”升级为“skill contract”

产出：

- `editorial-briefing` skill 接口
- 保留当前 RSS + search 混合逻辑
- 输出结构化中间结果

### Phase 2：Source Strategy 化

目标：

- 把 feeds/search 从配置项提升为策略项

产出：

- source adapters
- coverage check
- 补源决策

### Phase 3：轻量 Agent Runtime 化

目标：

- 让系统能按 mode 选择探索、补源和回退行为

产出：

- execution mode
- budget / retry / fallback
- diagnostics-first execution trace

---

## 15. 当前建议结论

建议正式采用以下命名：

- 总体能力层：**Editorial Intelligence Skill System**
- 第一核心 skill：**`editorial-briefing`**

并采用以下分层：

- `InsightBot`：产品与运营台
- `Editorial Intelligence Skill System`：底层能力层
- `editorial-briefing`：核心情报生产 skill

下一步最推荐做的事不是直接重写 runtime，而是：

1. 先确认这个命名和边界
2. 再写 `editorial-briefing` 的接口设计
3. 最后再把当前 `editorial_pipeline` 渐进迁入 skill contract

---

## 16. 一句话定义

**Editorial Intelligence Skill System** 是一个面向情报生产的能力层：它以 editorial workflow 为核心，支持多源混合检索、动态补源、结构化筛选、栏目分配、编辑成稿和诊断输出，并由 InsightBot 作为产品壳承载其长期运营与投递能力。
