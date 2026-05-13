# `editorial-briefing` 接口设计稿

> 状态：Draft  
> 归属：`editorial-intelligence` 新项目  
> 目标：定义第一核心 skill 的稳定输入输出接口，作为从 `InsightBot` 迁移底层执行能力的第一步

## 1. Skill 定位

`editorial-briefing` 是一个面向情报生产的核心 skill。

它不是调度器，不是控制台，也不是投递器。

它只负责一件事：

**基于 briefing goal、source strategy 和 editorial policy，产出一份结构化的 intelligence brief，并返回完整的中间结果和诊断信息。**

---

## 2. 设计目标

这个 skill 的接口需要满足以下目标：

1. 能承接当前 `editorial_pipeline` 的主要能力
2. 能从 RSS 扩展到 search 和未来平台源
3. 返回的不只是最终 Markdown，还包括中间状态
4. 能被 `InsightBot`、agent runtime、自动化任务共同调用
5. 允许未来增加更强的 agentic exploration，而不破坏接口

---

## 3. 顶层接口

建议第一版公共接口如下：

```python
from editorial_intelligence.skills.editorial_briefing import run_editorial_briefing

result = run_editorial_briefing(
    goal=goal,
    source_strategy=source_strategy,
    editorial_policy=editorial_policy,
    execution_mode="production_run",
)
```

或者对象式调用：

```python
skill = EditorialBriefingSkill()
result = skill.run(
    goal=goal,
    source_strategy=source_strategy,
    editorial_policy=editorial_policy,
    execution_mode="production_run",
)
```

---

## 4. 输入契约

### 4.1 `goal`

定义这次 briefing 要解决什么问题。

建议字段：

```json
{
  "topic": "中国 AI Agent 产品进展",
  "audience": "内部产品团队",
  "brief_type": "daily_brief",
  "focus_areas": ["产品发布", "能力升级", "商业化动作"],
  "exclusions": ["纯融资新闻"],
  "time_window": "24h",
  "quality_bar": "production"
}
```

字段说明：

- `topic`：主主题
- `audience`：读者是谁
- `brief_type`：日报、周报、专题快报
- `focus_areas`：重点关注维度
- `exclusions`：明确不收什么
- `time_window`：时间窗口
- `quality_bar`：结果质量要求

### 4.2 `source_strategy`

定义源的优先级、补源方式和探索边界。

建议字段：

```json
{
  "primary_sources": ["rss://36kr", "rss://producthunt"],
  "fallback_sources": ["rss://techcrunch"],
  "search_enabled": true,
  "platform_enabled": false,
  "max_explore_rounds": 2,
  "coverage_threshold": 0.7,
  "freshness_threshold_hours": 24,
  "source_constraints": {
    "language": "zh,en"
  }
}
```

字段说明：

- `primary_sources`：优先使用的源
- `fallback_sources`：主源不足时的回退源
- `search_enabled`：是否允许补搜索
- `platform_enabled`：是否允许平台适配器
- `max_explore_rounds`：最多补源轮数
- `coverage_threshold`：覆盖要求
- `freshness_threshold_hours`：新鲜度阈值
- `source_constraints`：源约束

### 4.3 `editorial_policy`

定义怎么筛、怎么分栏、怎么写。

建议字段：

```json
{
  "shortlist_size": 8,
  "selection_rules": [
    "优先保留对行业判断有价值的信息",
    "避免重复收录同一事件"
  ],
  "section_rules": {
    "产品动态": "优先放功能发布和能力升级",
    "市场信号": "优先放合作、商业化、渠道动作"
  },
  "dedupe_rules": [
    "同一事件跨源只保留一条主条目"
  ],
  "tone": "concise",
  "citation_style": "inline",
  "quality_checks": [
    "每条必须说明 why it matters"
  ]
}
```

### 4.4 `execution_mode`

控制这次执行更偏哪种行为。

支持枚举：

- `fast_run`
- `production_run`
- `explore_heavy`
- `source_constrained`
- `diagnostic_run`

建议语义：

- `fast_run`：少探索，优先快
- `production_run`：标准生产模式
- `explore_heavy`：优先补源和补覆盖
- `source_constrained`：严格限制只用指定源
- `diagnostic_run`：优先产出诊断和证据

---

## 5. 输出契约

skill 输出必须是结构化结果。

建议第一版 shape：

```json
{
  "ok": true,
  "source_summary": {
    "primary_used": 2,
    "fallback_used": 1,
    "search_used": true
  },
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
  }
}
```

### 5.1 `source_summary`

告诉上层：

- 这次用了哪些 source 类型
- 哪些是主源
- 哪些是回退源
- 是否用了搜索

### 5.2 `candidate_pool`

返回归一化后的候选池，便于：

- 控制台调试
- Prompt Debug
- 质量分析

### 5.3 `shortlist`

返回 shortlist 结果，而不只是最终成稿。

### 5.4 `section_assignments`

返回栏目归属结果，便于解释每条内容为何出现在对应 section。

### 5.5 `final_brief`

返回最终输出，可先只包含：

- `markdown`

后续可扩展：

- `blocks`
- `summary`
- `title`

### 5.6 `diagnostics`

第一版至少建议包含：

- `coverage_gaps`
- `source_failures`
- `needs_more_exploration`

后续可扩展：

- `low_confidence_sections`
- `duplicate_clusters`
- `source_quality_warnings`

---

## 6. 标准执行步骤

建议 skill 内部采用以下固定步骤：

1. Interpret goal
2. Build run-specific source strategy
3. Collect primary signals
4. Evaluate coverage and freshness
5. Supplement via fallback/search/platform if allowed
6. Normalize and dedupe
7. Run editorial shortlist
8. Assign items to sections
9. Refine section content
10. Assemble final brief
11. Emit diagnostics

这保证：

- 现有 `editorial_pipeline` 能自然迁入
- 未来引入 agent runtime 时也不必重写接口

---

## 7. 与现有 `editorial_pipeline` 的映射

建议这样看待迁移关系：

- 旧 `editorial_pipeline.py`：当前实现
- 新 `editorial-briefing`：稳定接口
- `editorial_pipeline`：新 skill 内部 workflow 名

也就是说：

- 继续保留 `editorial_pipeline` 作为内部执行流名
- 但对外统一暴露 `editorial-briefing`

这样命名更稳定。

---

## 8. 与 `InsightBot` 的边界

`InsightBot` 调用这个 skill 时，应该继续负责：

- 任务配置
- 调度
- 多频道投递
- 运行历史
- 验证与诊断 UI

这个 skill 自己只负责：

- 一次 briefing 的生产过程

不建议让 skill 负责：

- 直接发频道
- 直接管理任务状态
- 自己维护长期 run history

---

## 9. 第一版实现建议

第一版不要过度 agent 化。

建议节奏：

### Phase 1

先用 skill contract 包住当前 `editorial_pipeline`。

### Phase 2

把 RSS + search 抽成 adapter。

### Phase 3

再把 coverage check 和补源策略抽离成 runtime 行为。

这样迁移风险最小。

---

## 10. 当前建议结论

建议正式采用：

- 核心 skill 名：`editorial-briefing`
- 内部主流程名：`editorial_pipeline`

不建议直接把 skill 名叫成唯一的 `editorial-pipeline`，因为它太像内部流程，不像稳定对外能力接口。
