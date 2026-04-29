# Task Schema 重构：从 `feeds` 到 `sources + sections`

> 状态：In Progress  
> 目标分支：`dev-editorial` 后续演进  
> 背景：当前 InsightBot 已以 `editorial pipeline` 为主执行路径，现有任务配置模型需要与真实执行逻辑对齐

> 2026-04-29 更新：
> - `dev-editorial` 已完成 runtime / 控制台 / legacy editorial pipeline 的第一轮切换
> - 当前主模型已是 `sources + sections`
> - 运行时内部仍保留临时派生的 `feeds` 视图，用于兼容 Prompt Debug、健康检查和少量 legacy 路径

## 1. 问题定义

当前 `tasks.json` 里的任务配置仍然以 `feeds` 为中心：

```json
{
  "feeds": {
    "💡 营销行业": {
      "rss": ["..."],
      "keywords": ["..."],
      "prompt": "..."
    },
    "🤖 数智前沿": {
      "rss": ["..."],
      "keywords": ["..."],
      "prompt": "..."
    }
  }
}
```

这个结构来自 classic pipeline 时代，当时真实执行逻辑更接近：

1. 每个板块各抓各的源
2. 每个板块各自筛选
3. 最后拼接输出

但现在的 `editorial pipeline` 已经不是这样工作了。

它的真实执行逻辑是：

1. 所有源先汇总成统一候选池
2. 进行全局初筛
3. 将候选分配到栏目
4. 栏目内做最终精选和改写

也就是说，当前配置模型和实际执行模型之间已经出现了结构性错位：

- `feeds` 同时承担“信源池”和“栏目定义”两种职责
- `rss` 挂在栏目下，但实际抓取阶段是统一汇总的
- `keywords` 有时代表栏目主题，有时又被当作搜索 query 种子
- `prompt` 是栏目级策略，但和 RSS 放在一起，看起来像源配置的一部分

这会直接带来几个问题：

1. 控制台心智不清晰  
   用户会误以为“每个栏目只消费自己的那批源”，但 editorial 运行时不是这样。

2. Search 与 RSS 地位不对等  
   搜索现在只是“板块附属功能”，而不是一等 source strategy。

3. 扩展更多 source adapter 会很别扭  
   未来接平台源、API、社媒、人工种子源时，继续往 `feeds[*].rss` 里塞会越来越不合理。

4. skill 化方向受阻  
   `editorial-intelligence` 需要的其实是：
   - `source_strategy`
   - `editorial_policy`
   
   而不是一个混合了 source 和 section 含义的 `feeds`。

## 2. 重构目标

将任务配置模型拆成两个一等对象：

1. `sources`
   负责定义“从哪里抓”

2. `sections`
   负责定义“如何分栏、如何筛选、如何成稿”

一句话：

**信源是单独一层，栏目是单独一层。**

## 3. 新模型总览

建议未来的任务配置结构如下：

```json
{
  "tasks": {
    "daily_brief": {
      "name": "每日营销早报",
      "enabled": true,
      "pipeline": "editorial",
      "_editorial_pipeline_mode": "editorial-intelligence",
      "sources": {
        "rss": [
          {
            "id": "36kr_marketing",
            "url": "https://36kr.com/feed",
            "enabled": true,
            "tags": ["marketing", "industry"]
          },
          {
            "id": "producthunt_ai",
            "url": "https://www.producthunt.com/feed",
            "enabled": true,
            "tags": ["ai", "tools"]
          }
        ],
        "search": {
          "enabled": true,
          "provider": "baidu",
          "queries": [
            {
              "keywords": "品牌 AI 营销 新动作",
              "section_hints": ["🤖 数智前沿"],
              "max_results": 10
            },
            {
              "keywords": "微信生态 广告 营销",
              "section_hints": ["💡 营销行业"],
              "max_results": 10
            }
          ]
        }
      },
      "sections": {
        "💡 营销行业": {
          "prompt": "只保留与品牌营销、广告传播、平台经营动作直接相关的内容。",
          "keywords": ["营销", "广告", "品牌", "传播"],
          "source_hints": ["marketing", "industry"]
        },
        "🤖 数智前沿": {
          "prompt": "只保留 AI、自动化、数据能力对营销执行产生真实影响的内容。",
          "keywords": ["AI", "自动化", "智能广告", "数据能力"],
          "source_hints": ["ai", "tools"]
        }
      },
      "pipeline_config": {
        "global_shortlist_multiplier": 3,
        "assignment_batch_size": 20,
        "allow_multi_assign": false,
        "inject_publication_scope_into_global": true
      },
      "channels": ["wecom_main"],
      "schedule": {
        "hour": 8,
        "minute": 0
      }
    }
  }
}
```

## 4. 对象边界

### 4.1 `sources`

职责：定义候选池从哪里来。

建议包含：

- `rss`
- `search`
- 未来的 `platforms`
- 可选 `manual_seeds`

#### `sources.rss`

```json
{
  "id": "36kr_marketing",
  "url": "https://36kr.com/feed",
  "enabled": true,
  "tags": ["marketing", "industry"]
}
```

字段建议：

- `id`
  内部唯一标识，便于健康缓存、诊断和日志引用
- `url`
  RSS / Atom / RSSHub URL
- `enabled`
  是否启用
- `tags`
  可选标签，用于弱关联栏目，不是强绑定

#### `sources.search`

```json
{
  "enabled": true,
  "provider": "baidu",
  "queries": [
    {
      "keywords": "品牌 AI 营销 新动作",
      "section_hints": ["🤖 数智前沿"],
      "max_results": 10
    }
  ]
}
```

字段建议：

- `enabled`
- `provider`
  - `baidu`
  - `duckduckgo`
  - `brave`
  - `bocha`
- `queries`
- `queries[].keywords`
- `queries[].section_hints`
  从原来的单值 `category_hint` 升级成数组，表达“弱引导到哪些栏目”
- `queries[].max_results`

### 4.2 `sections`

职责：定义栏目策略，而不是定义抓取源。

#### `sections.<name>`

```json
{
  "prompt": "只保留与品牌营销、广告传播、平台经营动作直接相关的内容。",
  "keywords": ["营销", "广告", "品牌", "传播"],
  "source_hints": ["marketing", "industry"]
}
```

字段建议：

- `prompt`
  栏目级最终精选规则
- `keywords`
  栏目主题关键词，可用于：
  - query seed 建议
  - assignment hint
  - coverage diagnosis
- `source_hints`
  用于弱引导栏目与 source tags 之间的关系

注意：

`sections` 不直接挂 RSS URL。  
栏目可以“偏向”某些源，但不再“拥有”某些源。

## 5. 为什么这更符合 editorial pipeline

### 当前真实执行路径

```text
RSS / Search / Other Sources
        ↓
统一候选池
        ↓
全局初筛
        ↓
栏目分配
        ↓
栏目内精选
        ↓
简报输出
```

### 旧模型的问题

旧模型会让人误读成：

```text
栏目 A -> 自己的 RSS -> 自己筛
栏目 B -> 自己的 RSS -> 自己筛
```

这和 editorial pipeline 已经不一致。

### 新模型的好处

1. 配置和执行逻辑对齐
2. Search 与 RSS 成为同等 source
3. 栏目更像真正的 editorial policy
4. 更贴近 `editorial-intelligence` 的 `source_strategy + editorial_policy`
5. 后续扩展平台源时不需要继续污染栏目结构

## 6. 控制台信息架构建议

如果按新模型走，任务配置页建议拆成这几段：

1. 基本信息
   - 任务名
   - pipeline
   - channels
   - schedule

2. 信源池
   - RSS 源列表
   - 启用/停用
   - source tags
   - 健康度

3. 搜索补充
   - provider
   - queries
   - section hints

4. 栏目定义
   - 栏目名
   - prompt
   - keywords
   - source hints

5. Editorial Pipeline 策略
   - shortlist multiplier
   - assignment batch size
   - multi-assign
   - inject publication scope

这样控制台心智会更清楚：

- “从哪里抓” 在一起
- “怎么分栏” 在一起
- “怎么跑” 在一起

## 7. 运行时映射

新 schema 应直接映射到 skill/runtime 语义。

### `sources` → `SourceStrategy`

- `sources.rss` → `primary_sources`
- `sources.search.enabled` → `search_enabled`
- `sources.search.queries` → `goal.queries` 或 `source_constraints`
- `source tags` / `section_hints` → assignment hints / ranking hints

### `sections` → `EditorialPolicy`

- `sections[*].prompt` → section-level filtering policy
- `sections[*].keywords` → section rules / assignment hints
- `sections[*].source_hints` → weak source bias

换句话说，新 schema 不是只为控制台服务，而是为了让产品配置更自然地进入 `editorial-intelligence`。

## 8. 不做兼容层的迁移策略

这次建议 **不做 `feeds -> sources + sections` 的长期兼容层**。

原因：

1. 当前任务规模不大
2. 旧模型已经开始误导使用者
3. 长期兼容会把控制台、loader 和 pipeline 都拖进双模型维护
4. 现在正是切模型的合适窗口

### 迁移方式

采用一次性手动迁移：

#### 从旧 `feeds` 提取到新 `sources`

旧：

```json
"feeds": {
  "💡 营销行业": {
    "rss": ["https://a.com/rss", "https://b.com/rss"],
    "keywords": ["营销", "广告"],
    "prompt": "..."
  }
}
```

新：

```json
"sources": {
  "rss": [
    {"id": "a_com_rss", "url": "https://a.com/rss", "enabled": true, "tags": ["marketing"]},
    {"id": "b_com_rss", "url": "https://b.com/rss", "enabled": true, "tags": ["marketing"]}
  ]
}
```

#### 从旧 `feeds` 提取到新 `sections`

旧：

```json
"feeds": {
  "💡 营销行业": {
    "keywords": ["营销", "广告"],
    "prompt": "..."
  }
}
```

新：

```json
"sections": {
  "💡 营销行业": {
    "prompt": "...",
    "keywords": ["营销", "广告"],
    "source_hints": ["marketing"]
  }
}
```

#### 从旧 `search` 升级

旧：

```json
"search": {
  "enabled": true,
  "provider": "baidu",
  "queries": [
    {
      "keywords": "品牌 AI 营销 新动作",
      "category_hint": "🤖 数智前沿",
      "max_results": 10
    }
  ]
}
```

新：

```json
"sources": {
  "search": {
    "enabled": true,
    "provider": "baidu",
    "queries": [
      {
        "keywords": "品牌 AI 营销 新动作",
        "section_hints": ["🤖 数智前沿"],
        "max_results": 10
      }
    ]
  }
}
```

## 9. 对代码层的影响

### 需要调整的地方

1. `tasks.json` schema
2. `scripts/app.py`
   - 任务配置页 UI
   - 健康度页 source 展示
3. `insightbot/config.py`
   - `load_tasks_config()`
4. `insightbot/editorial_pipeline.py`
   - `build_global_candidates()`
   - `search_global_candidates()`
   - section assignment 输入
5. `insightbot/task_validation.py`
   - 从校验 `feeds` 改为校验 `sources + sections`
6. `editorial-intelligence` bridge
   - 直接吃新 schema，减少中间映射扭曲

### 暂时不需要改的地方

1. `task_runner` 的 dry run / history / channel send 结构
2. `run_history`
3. `task_state`
4. `task_health_store`

也就是说，这次主要是 **任务配置层 + pipeline 输入层** 的重构，不是整个系统重写。

## 10. 建议实施顺序

### Phase 1

先定义并落地新 schema：

- `sources`
- `sections`
- `pipeline_config`

但先不改控制台，只允许通过手工编辑 `tasks.json` 验证执行链。

### Phase 2

更新 loader 与 editorial pipeline：

- 让执行逻辑以 `sources + sections` 为主

### Phase 3

重构控制台任务配置页：

- 信源池
- 搜索补充
- 栏目定义

### Phase 4

移除旧 `feeds` 逻辑：

- 不再读旧结构
- 不再展示旧 UI

## 11. 建议结论

对于 `editorial pipeline` 主导的未来形态，任务配置模型应该从：

**`feeds + search + prompt` 的混合结构**

升级为：

**`sources + sections + pipeline_config` 的分层结构**

这不是纯粹的“代码整理”，而是：

**让产品配置模型真正对齐 editorial 执行模型和 skill 化方向。**

## 12. 代码落地清单

这一节只回答一个问题：

**如果现在开始动代码，具体该改哪里，按什么顺序改。**

### 12.1 P0：先把运行时吃新 schema 跑通

目标：

- 不先碰大 UI
- 先让 `tasks.json` 里手写的新结构能真实执行

涉及文件：

1. `insightbot/config.py`
2. `insightbot/task_runner.py`
3. `insightbot/task_validation.py`
4. `tests/test_task_runner.py`
5. `tests/test_task_validation.py`

具体动作：

#### `insightbot/config.py`

新增一层任务装配逻辑：

- 读取 `task_def["sources"]`
- 读取 `task_def["sections"]`
- 保留 `_task_channels`
- 保留 `_task_pipeline`
- 保留 `_editorial_pipeline_mode`
- 保留 `_task_name`

建议新增 helper：

```python
def _assemble_task_sources(task_def: dict) -> dict: ...
def _assemble_task_sections(task_def: dict) -> dict: ...
```

运行时返回值建议变成：

```python
config["sources"] = deepcopy(task_def.get("sources", {}))
config["sections"] = deepcopy(task_def.get("sections", {}))
config["search"] = deepcopy(task_def.get("sources", {}).get("search", {}))
```

注意：

- 这里不再把 `feeds` 当正式结构继续注入
- `search` 可以暂时保留一份平铺副本，只是为了减少后续 bridge 改动量

#### `insightbot/task_runner.py`

当前 `_run_editorial_intelligence_pipeline()` 还是从：

- `config["feeds"]`
- `config["search"]`

推导 runtime 输入。

需要改成优先读取：

- `config["sources"]`
- `config["sections"]`

建议新增 helper：

```python
def _collect_primary_sources(config: dict) -> list[str]: ...
def _build_goal_from_sections(config: dict) -> dict: ...
def _normalize_search_queries_from_sources(search_config: dict) -> list[str]: ...
```

这里最关键的变化：

- `goal.topic` 不再简单由 `feeds.keys()` 拼接
- 应优先由 `sections.keys()` 生成
- `primary_sources` 直接来自 `sources.rss[*].url`
- `search_config` 直接来自 `sources.search`

#### `insightbot/task_validation.py`

从校验：

- `feeds`
- `feeds[*].rss`

切到校验：

- `sources.rss`
- `sources.search`
- `sections`

最低校验规则建议更新为：

1. 没有 `sections`
2. 没有任何启用的 RSS 源，且 search 也未启用
3. `sources.search.enabled=true` 但 query 为空
4. `sections[*].prompt` 为空时给 warning
5. `channels` 缺失
6. `schedule` 缺失
7. `pipeline` 非法

summary 也要改口径：

```python
{
  "section_count": ...,
  "rss_source_count": ...,
  "search_query_count": ...,
  "channel_count": ...,
}
```

### 12.2 P1：让控制台能编辑新 schema

目标：

- 不再让用户继续编辑旧 `feeds`
- 控制台正式切成 `信源池 + 搜索补充 + 栏目定义`

涉及文件：

1. `scripts/app.py`
2. `scripts/ui/task_config.py`
3. 后续如继续拆分，可新增：
   - `scripts/ui/task_sources.py`
   - `scripts/ui/task_sections.py`

具体动作：

#### `scripts/app.py`

当前任务管理页核心还是：

- `feeds_editor`
- `search_config`
- `pipeline_config`

需要改成：

- `sources_rss_editor`
- `sources_search_editor`
- `sections_editor`
- `pipeline_config`

这不是简单改字段名，而是改表单结构：

1. 基本信息
2. 信源池
3. 搜索补充
4. 栏目定义
5. Editorial Pipeline 策略
6. 高级 AI 设置

搜索区要同步改这些细节：

- `category_hint` → `section_hints`
- 单选 → 多选
- “从板块关键词派生” → “从栏目关键词派生”

#### `scripts/ui/task_config.py`

当前最小可运行向导仍然会写：

```python
updated_task["feeds"][category_name]["rss"]
```

需要改成：

- 新建一个默认 section
- 新建一个默认 RSS source

建议最小保存结果直接写：

```python
updated_task["sources"]["rss"] = [...]
updated_task["sections"][category_name] = {
  "prompt": "",
  "keywords": [],
  "source_hints": [],
}
```

也就是说，这个向导要从“补一个 feeds 板块”改成“补一个 section + 一个 source”。

### 12.3 P2：让 legacy editorial pipeline 也吃新结构

目标：

- 即使 `_editorial_pipeline_mode != editorial-intelligence`
- 旧 `insightbot/editorial_pipeline.py` 也能跑新 schema

涉及文件：

1. `insightbot/editorial_pipeline.py`
2. `tests/test_editorial_pipeline.py`

建议做法：

- `build_global_candidates()` 改为优先读取 `sources.rss`
- 搜索补充优先读取 `sources.search`
- 栏目列表优先读取 `sections.keys()`
- section prompt / keywords 从 `sections[*]` 读取

这样可以让：

- legacy editorial
- editorial-intelligence

都站到同一个任务 schema 上。

### 12.4 P3：删旧结构

目标：

- 彻底结束双心智

涉及文件：

1. `scripts/app.py`
2. `scripts/ui/task_config.py`
3. `insightbot/config.py`
4. `insightbot/task_validation.py`
5. `insightbot/task_runner.py`
6. README / docs / deployment guides

完成标准：

- 控制台不再出现 `feeds`
- 代码主路径不再依赖 `feeds`
- 验证器不再校验 `feeds`
- 文档不再把 `feeds` 视为当前主模型

## 13. 一次性迁移步骤

因为这次明确 **不做长期兼容层**，所以迁移必须足够直接。

建议按这个顺序做：

### Step 1：先冻结生产任务清单

为当前腾讯云 / 本地实际在跑的任务导出一份只读快照：

- `tasks.json`
- `channels.json`
- `config.content.json`

目的：

- 避免迁移时丢 prompt、RSS、search query、schedule

### Step 2：手工改写任务

按下面映射改：

- `feeds[*].rss` → `sources.rss[*]`
- `feeds[*].prompt` → `sections[*].prompt`
- `feeds[*].keywords` → `sections[*].keywords`
- `search.queries[*].category_hint` → `sources.search.queries[*].section_hints`

### Step 3：本地只跑一个任务做验证

先不要全量切。

本地验证至少跑：

1. `python -m insightbot --task <task_id> --dry-run`
2. 控制台保存并重开任务
3. `验证与调试` 页可读健康状态
4. `editorial-intelligence` 路径 search query 生效

### Step 4：再切生产

生产切换顺序建议：

1. 备份旧 `tasks.json`
2. 上传新 `tasks.json`
3. 重启 `insightbot-scheduler`
4. 先看一次 Dry Run
5. 再等下一个正式调度周期

### Step 5：观察三类信号

迁移后重点只盯三件事：

1. search query 是否按新配置执行
2. 候选是否能正常分配到 sections
3. 最终发送内容是否仍然完整

## 14. 推荐实施切片

如果按最稳的切片推进，我建议拆成这 4 个小 PR / commit：

1. `schema(runtime): load sources and sections in config/task runner`
2. `schema(validation): validate sources and sections`
3. `console(task-config): replace feeds editor with sources and sections editor`
4. `schema(cleanup): remove legacy feeds path`

这样每一轮都能单独验证，不会把“模型迁移”和“控制台改版”完全绑死。
