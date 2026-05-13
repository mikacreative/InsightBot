# 新项目启动稿：Editorial Skill Runtime

> 状态：Draft  
> 用途：为“面向情报生产的 agent skill system”单独起一个新项目时，提供 README 草稿、架构骨架和目录设计  
> 关系：该项目将作为 `InsightBot` 的底层能力核，被产品层调用

## 1. 先回答命名问题

你提到想把这个 skill 叫做 `editorial pipeline`。

我的判断是：

- **作为内部流程名，可以继续保留 `editorial pipeline`**
- **作为新项目名，不建议直接叫 `editorial-pipeline`**
- **作为核心 skill 名，也不建议直接只叫 `editorial-pipeline`**

原因很简单：

### `editorial pipeline` 的优点

- 你们团队已经熟悉这个词
- 它准确描述了“编辑式筛选与成稿流程”
- 用来指当前这条主流程非常自然

### `editorial pipeline` 的问题

- 它更像“流程名”，不像“产品名 / 项目名 / 能力系统名”
- 它没有表达多源探索、补源、诊断、source strategy 这些新能力
- 听起来更像现有 `InsightBot` 里的一个 pipeline，而不是一个独立能力核

所以我建议这样分层命名：

### 推荐命名层级

- 新项目名：`editorial-intelligence`
- 核心 skill 名：`editorial-briefing`
- 主要执行流名：`editorial_pipeline`

这样三者分工很清楚：

- `editorial-intelligence`：项目 / repo / package 名
- `editorial-briefing`：对外的核心 skill
- `editorial_pipeline`：skill 内部的一条主执行流

### 备选方案

如果你特别想保留 `pipeline` 这个词，可以考虑：

- 项目名：`editorial-runtime`
- skill 名：`editorial-briefing`
- 内部执行流：`editorial_pipeline`

或者：

- 项目名：`editorial-briefing`
- skill 名：`editorial-briefing`
- 内部执行流：`editorial_pipeline`

但我整体还是更推荐：

**项目名：`editorial-intelligence`**

因为它比 `pipeline` 更大一层，更能容纳你未来想加入的：

- RSS
- Search
- Platform adapters
- 多轮探索
- 诊断输出
- source strategy

---

## 2. 新项目一句话定义

`editorial-intelligence` 是一个面向情报生产的能力核：它以 editorial workflow 为核心，支持多源混合检索、动态补源、结构化筛选、栏目分配、编辑成稿和诊断输出，并通过 skill contract 被上层产品或 agent 调用。

---

## 3. 这个新项目的定位

这个项目不是：

- 控制台
- 多任务后台
- 调度中心
- 频道发送系统

这个项目是：

- skill runtime
- source adapter framework
- editorial reasoning workflow
- briefing result contract

一句更直接的话：

**InsightBot 负责运营，`editorial-intelligence` 负责生产。**

---

## 4. README 草稿

下面这版可以直接作为新 repo 的 `README.md` 初稿。

---

# editorial-intelligence

Editorial intelligence runtime for multi-source briefing workflows.

`editorial-intelligence` is a skill-oriented runtime for producing structured intelligence briefs.  
It is designed to power products like `InsightBot`, but can also be used independently by agents, automations, and internal research workflows.

## What It Does

The system is built around an editorial workflow rather than a fixed RSS script.

It supports:

- multi-source collection
- source strategy and fallback logic
- normalized candidate pools
- editorial shortlist and assignment
- section-level refinement
- final brief generation
- diagnostic output

## What It Is Not

This project is not a control console, task scheduler, or channel delivery system.

Those concerns belong to product layers such as `InsightBot`.

This project focuses on the execution core:

- source adapters
- runtime orchestration
- skill contracts
- briefing workflows

## Core Concepts

### Skill

A reusable execution contract for a class of work.

The first core skill is:

- `editorial-briefing`

### Runtime

The runtime coordinates execution steps, source adapters, fallback paths, and diagnostics.

### Source Strategy

A structured policy for deciding where to gather signals from:

- RSS
- Search
- Platform adapters
- Future APIs / internal data sources

### Editorial Workflow

The canonical workflow is:

1. interpret goal
2. collect signals
3. fill coverage gaps
4. normalize and dedupe
5. shortlist
6. assign to sections
7. refine and compose
8. emit diagnostics and final brief

## Planned Package Structure

```text
editorial_intelligence/
  runtime/
  skills/
  adapters/
  contracts/
  workflows/
  diagnostics/
  policies/
  storage/
  utils/
```

## First Skill

`editorial-briefing`

Input:

- briefing goal
- source strategy
- editorial policy
- execution mode

Output:

- source summary
- candidate pool
- shortlist
- section assignments
- final brief
- diagnostics

## Relationship to InsightBot

`InsightBot` should call this project as its execution core.

Recommended split:

- `InsightBot`: tasks, channels, scheduling, operations console, run history
- `editorial-intelligence`: source collection, editorial reasoning, brief generation

## Development Stages

### Phase 1

Wrap the current editorial pipeline in a skill contract.

### Phase 2

Introduce structured source strategies and adapter-based source expansion.

### Phase 3

Add a lightweight agent runtime for exploration, fallback, and execution modes.

---

## 5. 建议的 repo 结构

下面这版是我建议的新项目第一版目录骨架。

```text
editorial-intelligence/
├─ README.md
├─ pyproject.toml
├─ docs/
│  ├─ architecture.md
│  ├─ skills/
│  │  └─ editorial-briefing.md
│  ├─ adapters/
│  │  ├─ rss.md
│  │  ├─ search.md
│  │  └─ platform.md
│  └─ migration/
│     └─ from-insightbot-editorial-pipeline.md
├─ editorial_intelligence/
│  ├─ __init__.py
│  ├─ runtime/
│  │  ├─ __init__.py
│  │  ├─ engine.py
│  │  ├─ context.py
│  │  ├─ executor.py
│  │  ├─ modes.py
│  │  ├─ budget.py
│  │  └─ errors.py
│  ├─ skills/
│  │  ├─ __init__.py
│  │  ├─ registry.py
│  │  └─ editorial_briefing/
│  │     ├─ __init__.py
│  │     ├─ skill.py
│  │     ├─ goal.py
│  │     ├─ workflow.py
│  │     ├─ prompts.py
│  │     ├─ result.py
│  │     └─ validators.py
│  ├─ adapters/
│  │  ├─ __init__.py
│  │  ├─ base.py
│  │  ├─ rss.py
│  │  ├─ search.py
│  │  ├─ platform.py
│  │  └─ registry.py
│  ├─ workflows/
│  │  ├─ __init__.py
│  │  ├─ editorial_pipeline.py
│  │  ├─ shortlist.py
│  │  ├─ assignment.py
│  │  ├─ refine.py
│  │  └─ assemble.py
│  ├─ contracts/
│  │  ├─ __init__.py
│  │  ├─ goal.py
│  │  ├─ source_strategy.py
│  │  ├─ editorial_policy.py
│  │  ├─ execution_mode.py
│  │  └─ briefing_result.py
│  ├─ diagnostics/
│  │  ├─ __init__.py
│  │  ├─ coverage.py
│  │  ├─ source_failures.py
│  │  ├─ run_trace.py
│  │  └─ quality.py
│  ├─ policies/
│  │  ├─ __init__.py
│  │  ├─ source_strategy.py
│  │  ├─ dedupe.py
│  │  ├─ ranking.py
│  │  └─ section_rules.py
│  ├─ storage/
│  │  ├─ __init__.py
│  │  ├─ artifacts.py
│  │  └─ cache.py
│  └─ utils/
│     ├─ __init__.py
│     ├─ time.py
│     ├─ text.py
│     └─ ids.py
├─ tests/
│  ├─ runtime/
│  ├─ skills/
│  ├─ adapters/
│  ├─ workflows/
│  └─ diagnostics/
└─ examples/
   ├─ run_editorial_briefing.py
   └─ insightbot_integration.py
```

---

## 6. 为什么这样分目录

### `runtime/`

这一层解决：

- 一次执行怎么被组织
- 执行模式如何控制
- 超时、预算、错误怎么管理

这里不写具体业务逻辑，只写运行机制。

### `skills/`

这一层放 skill contract 和 skill-specific 逻辑。

`editorial_briefing/` 单独成目录，是因为它迟早会成为一个完整子系统，而不是一个单文件。

### `adapters/`

这一层专门处理多源输入。

好处是以后接：

- search
- 平台抓取
- API
- 内部知识源

都不会污染 skill 主体。

### `workflows/`

这一层放“如何处理内容”的步骤实现。

我建议保留 `editorial_pipeline.py` 这个文件名，因为它在语义上仍然成立：

- 它代表 skill 内部的主执行流
- 但它不再等于整个项目本身

这就是我前面说的：

- `editorial pipeline` 适合作为流程名
- 不适合作为整个 repo 的名字

### `contracts/`

这一层非常关键，它决定这个项目能不能被别的产品接入。

如果没有这一层，项目很容易重新滑回“脚本仓库”。

### `diagnostics/`

把诊断单独拉出来，是因为你们现在已经明显走向“诊断优先”的产品心智：

- 为什么没产出
- 为什么结果太少
- 为什么源不够好

这不应只是控制台 UI 逻辑，而应成为底层执行结果的一部分。

---

## 7. 第一版最小架构

不要一开始就做成复杂 agent 平台。

第一版应当足够小，但结构正确。

### 第一版一定要有

- `editorial_briefing.skill`
- `contracts/*`
- `adapters/rss.py`
- `adapters/search.py`
- `workflows/editorial_pipeline.py`
- `diagnostics/coverage.py`
- `diagnostics/source_failures.py`

### 第一版可以先不做

- 通用 plugin marketplace
- 复杂 agent planning
- 多 skill 并发编排
- 可视化控制台
- 完整长时记忆

目标不是“大而全”，而是：

**先把“可扩展的情报生产 skill contract”立住。**

---

## 8. 第一版核心接口建议

我建议新项目最先暴露的 public API 很简单：

```python
from editorial_intelligence.skills.editorial_briefing import run_editorial_briefing

result = run_editorial_briefing(
    goal=...,
    source_strategy=...,
    editorial_policy=...,
    execution_mode="production_run",
)
```

返回：

```python
{
    "ok": True,
    "source_summary": {...},
    "candidate_pool": [...],
    "shortlist": [...],
    "section_assignments": {...},
    "final_brief": {"markdown": "..."},
    "diagnostics": {...},
}
```

这个接口一旦立住，`InsightBot` 以后就能把自己的 `task_runner` 接过来。

---

## 9. 与当前 InsightBot 的迁移关系

建议迁移策略如下：

### Stage 1：镜像实现

先在新项目里重建当前 `editorial_pipeline` 的核心流程，但接口改为 skill contract。

### Stage 2：由 InsightBot 调用新 skill

`InsightBot.task_runner` 不再直接依赖旧 `editorial_pipeline.py`，而是调用新项目暴露的 skill。

### Stage 3：旧 pipeline 逐步退役

等新 skill 稳定以后，再逐步下掉旧实现。

这样迁移风险最小。

---

## 10. 当前建议

如果你决定另起项目，我建议这样定：

### 项目名

**`editorial-intelligence`**

### Python package 名

**`editorial_intelligence`**

### 核心 skill 名

**`editorial-briefing`**

### 内部主流程名

**`editorial_pipeline`**

这套命名组合我觉得最稳，也最方便后续扩展。

---

## 11. 一句话结论

如果要把现有 InsightBot 的底层能力升级成一个真正可复用、可扩展、可被其他 agent 调用的能力核，那么最合理的做法不是继续把所有逻辑堆在原仓库里，而是单独起一个名为 **`editorial-intelligence`** 的新项目：其中 `editorial-briefing` 作为核心 skill，`editorial_pipeline` 作为其内部主执行流，由 InsightBot 继续承担产品壳与运营台职责。
