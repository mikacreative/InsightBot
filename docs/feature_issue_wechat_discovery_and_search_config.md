# Feature Issue: Search Config Rationalization and WeChat Discovery Layer

## Goal

把当前 `Daily_brief` 的搜索补充能力从“能跑”收口成“可解释、可维护、可扩展”，并为微信生态内容发现建立一层明确的 `discovery + resolver` 能力，而不是继续把搜索结果页直接当成候选内容源。

## Why

当前这层能力存在三个结构性问题：

1. `search` 的任务级配置已经存在，但生产环境与仓库配置仍然容易漂移。
2. 搜索结果既承担“发现线索”又承担“直接入池”的角色，容易把列表页、跳转页、搜索落地页误当成文章页。
3. 微信生态的直连 feed 不稳定且覆盖有限，实际又确实需要一个可持续的发现窗口。

## Problem Statement

当前系统里，`search` 的角色不够清晰：

- 一部分逻辑把它当成 RSS 的补充抓取器
- 一部分逻辑把它当成文章候选直接来源
- 但对微信生态来说，搜索结果页通常不是 canonical article URL

这会导致两类问题：

1. 运行质量问题
   - 搜到 `weixin.sogou.com/weixin?...` 这类搜索结果页
   - 链接本身不可直接投递
   - 即使标题像正文，也可能只是搜索落地页

2. 配置治理问题
   - task-level `search` 已经存在，但 provider、query 模板、开关策略缺乏统一规则
   - UI、任务配置和运行态之间容易出现“看起来不一致”的状态

## Scope

本 feature 只覆盖以下范围：

1. 任务级 `search` 配置模型收口
2. 微信生态 `discovery` 层设计
3. 搜索结果到正文链接的 `resolver` 层设计
4. UI 对 search 状态的表达与验证

不包含：

- 新增更多推送渠道
- 大规模重写 editorial pipeline
- 直接接入复杂的飞书/微信应用消息能力

## Proposed Direction

### 1. Separate discovery from content ingestion

不要再把搜索结果直接当成最终候选内容。

改成两层：

- `discovery layer`
  - 负责根据 query 找到候选线索
  - 输出的是 `discovery candidates`
- `resolver layer`
  - 负责判断候选是不是正文页
  - 如果不是正文页，尝试解析出 canonical article URL
  - 解析失败则丢弃

### 2. Reframe WeChat discovery as a first-class capability

微信生态内容发现应该被明确建模，而不是塞进普通 search provider。

建议新增能力边界：

- `provider`: 仍然可以有 `baidu / bocha / brave / duckduckgo`
- `source_type`: 明确区分 `web_search / wechat_discovery / direct_feed`

这样搜狗或其他微信搜索入口如果要接入，也不是“再加一个 provider”，而是：

- 作为 `wechat_discovery` 的实现细节
- 输出待解析的线索，不直接进入主候选池

### 3. Introduce canonical URL quality gates

对 discovery 结果增加统一判定：

- 是否为列表页
- 是否为搜索结果页
- 是否为跳转页
- 是否为正文页
- 是否可提取 canonical URL

如果命中以下任一情况，应阻止入池：

- `sogou weixin search result`
- `baidu result landing page`
- `account home / author page`
- `feed index / tag page / topic page`

### 4. Make search state explicit in task schema and UI

把 search 的配置和状态拆清楚：

- `enabled`
- `provider`
- `intent`
  - `supplement`
  - `discovery_only`
- `queries`
- `resolver_required`

UI 上至少应明确显示：

- 当前 search 是否真的启用
- 当前 query 数量
- 当前 provider
- 当前模式是“直接补充”还是“discovery only”

## Suggested Task Breakdown

### Phase 1: Config cleanup

- 统一 task schema 中 `sources.search` 的字段定义
- 收口默认值与 migration
- 校正 UI 与 runtime 的状态映射

### Phase 2: Discovery model

- 引入 discovery candidate 数据结构
- 区分 `content candidates` 与 `discovery candidates`
- 在 pipeline 中增加 resolver 前置阶段

### Phase 3: WeChat discovery implementation

- 评估搜狗、百度等入口是否适合作为微信发现窗口
- 实现至少一种 `wechat discovery` provider
- 输出标准化 discovery result

### Phase 4: Resolver and guardrails

- canonical URL 解析
- result-page / list-page / redirect-page 拦截
- 失败时打点并记录原因

## Acceptance Criteria

满足以下条件，才算完成：

1. UI 能准确反映 task 当前 search 状态，不出现“运行已启用但界面像未启用”的歧义。
2. 搜索结果页、列表页、跳转页不能再直接进入最终候选池。
3. 微信 discovery 能输出结构化候选，并经过 resolver 后才进入 editorial pipeline。
4. `Daily_brief` 在保留 search 补充能力的前提下，不再产出 `sogou/baidu` 落地页链接。
5. 相关日志和调试面板能区分：
   - `rss candidates`
   - `search discovery candidates`
   - `resolved canonical candidates`
   - `dropped candidates`

## Open Questions

1. 搜狗是否值得作为首个 `wechat_discovery` provider，还是先做一个通用 resolver 再决定 provider？
2. 对微信生态来说，我们是否还要维护一份“优先直连 feed 名单”，而 discovery 只作为补充？
3. `search` 是否默认都应切到 `discovery_only`，避免未来再出现搜索页误入池？

## Recommended Default

推荐默认路线：

1. 先做 `search config` 收口
2. 再做 `resolver`
3. 最后再引入 `wechat_discovery`

原因很简单：如果没有 resolver，越早引入微信 discovery，越容易把坏链接规模化带进系统。
